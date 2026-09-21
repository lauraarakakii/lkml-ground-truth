"""Pipeline orchestration from one or more datasets to match CSV files.

This module handles I/O and ``multiprocessing.Pool``. Patch-to-commit
comparison lives in :mod:`lkml_ground_truth.engine`.
"""

from __future__ import annotations

import logging
from multiprocessing import Pool
from pathlib import Path

import dataclasses
from concurrent.futures import ThreadPoolExecutor, as_completed
import polars as pl

from .config import Config
from .dataset_io import read_parquet_safe
from .engine import init_worker_globals, process_row
from .repo_setup import ensure_repo


logger = logging.getLogger(__name__)
_RESULT_SCHEMA = {
    "message_id": pl.Utf8,
    "best_commit": pl.Utf8,
    "score": pl.Float64,
    "is_match": pl.Boolean,
    "is_confident_match": pl.Boolean,
    "error": pl.Utf8,
}

def _checkpoint_path(output_path: str) -> Path:
    return Path(output_path).with_suffix(".ckpt")

def _load_checkpoint(output_path: str) -> tuple[list[dict], set[str]]:
    """Load a checkpoint when present and return completed results and IDs."""
    ckpt = _checkpoint_path(output_path)
    if not ckpt.exists():
        return [], set()
    try:
        logger.info("Checkpoint found: %s; loading...", ckpt)
        df = pl.read_csv(ckpt, schema_overrides=_RESULT_SCHEMA)
        rows = df.to_dicts()
        ids = {r["message_id"] for r in rows if r.get("message_id")}
        logger.info(
            "Checkpoint found: %d rows already processed (%s); resuming.",
            len(rows),
            ckpt,
        )
        return rows, ids
    except Exception as exc:
        logger.warning(
            "Could not load checkpoint (%s): %s. Starting from scratch.", ckpt, exc
        )
        return [], set()

def _append_checkpoint(ckpt: Path, new_rows: list[dict]) -> None:
    if not new_rows:
        return
    ckpt.parent.mkdir(parents=True, exist_ok=True)
    write_header = not ckpt.exists() or ckpt.stat().st_size == 0
    df = pl.DataFrame(new_rows, schema=_RESULT_SCHEMA, infer_schema_length=None)
    with open(ckpt, "ab") as f:
        df.write_csv(f, include_header=write_header)

def process_list(config: Config, list_name: str) -> None:
    """Process one dataset list from a ``list=<name>`` directory."""
    glob_path = config.paths.parquet_glob(list_name)
    output_path = config.paths.resolved_output_path(list_name)

    logger.info("=== List: %s ===", list_name)
    logger.info("Loading dataset: %s", glob_path)
    df = read_parquet_safe(glob_path)
    df_patches = df.filter(pl.col("code").is_not_null())
    logger.info("-> %d emails with a diff (out of %d total)", df_patches.height, df.height)

    prior_results, done_ids = _load_checkpoint(output_path)
    if done_ids:
        df_patches = df_patches.filter(~pl.col("message_id").is_in(done_ids))
        logger.info(
            "-> %d emails remaining after checkpoint (out of %d total)",
            df_patches.height,
            df.height
        )

    if df_patches.height == 0 and not prior_results:
        logger.info("Nothing to process for this list.")
        return

    ckpt = _checkpoint_path(output_path)
    results: list[dict] = list(prior_results)

    if df_patches.height > 0:
        num_workers = config.performance.resolved_num_workers()
        logger.info(
            "Processing with %d worker process(es) "
            "(configure performance.num_workers in config.toml)...",
            num_workers,
        )

    checkpoint_every = config.performance.checkpoint_every
    batch: list[dict] = []
    rows_iter = df_patches.iter_rows(named=True)

    with Pool(num_workers) as pool:
        for i, result in enumerate(
            pool.imap_unordered(
                process_row, rows_iter, chunksize=config.performance.chunksize
            ), 
            start=1,
        ):
            if result is not None:
                results.append(result)
                batch.append(result)
            if checkpoint_every > 0 and len(batch) >= checkpoint_every:
                _append_checkpoint(ckpt, batch)
                logger.info(
                    "Checkpoint saved (%d rows) at %s", len(batch), ckpt
                )
                batch.clear()
            if i % config.performance.progress_every == 0 or i == df_patches.height:
                logger.info("processed %d/%d...", i, df_patches.height)

    if batch and checkpoint_every > 0:
        _append_checkpoint(ckpt, batch)
        logger.info(
            "Final checkpoint saved (%d rows) at %s", len(batch), ckpt
        )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    if not results:
        logger.info("No results: no row contained a usable diff.")
        pl.DataFrame(schema=_RESULT_SCHEMA).write_csv(output_path)
        return
    else:
        out = pl.DataFrame(results, infer_schema_length=None)
        out.write_csv(output_path)
        logger.info("Done. Results saved to %s", output_path)
        logger.info("%s", out.group_by("is_match").len())
        n_errors = out.filter(pl.col("error").is_not_null()).height
        if n_errors:
            logger.warning("%d rows had errors; see the CSV error column.", n_errors)

    if ckpt.exists():
        ckpt.unlink()
        logger.debug("Removed checkpoint: %s", ckpt)

def run(config: Config) -> None:
    """Pipeline entry point: validate the repository and process selected lists."""
    ensure_repo(config.repo, config.paths.repo_path)

    logger.info(
        "Opening repository and building/loading index: %s", config.paths.repo_path
    )
    init_worker_globals(config)  

    list_name = config.paths.list_name
 
    if list_name.lower() in ("all", "*"):
        available = config.paths.available_lists()

        n_parallel = config.performance.resolved_parallel_lists(len(available))
        logger.info(
            "list_name = '%s' -> processing %d lists (%d concurrently) from %s",
            list_name,
            len(available),
            n_parallel,
            config.paths.dataset_root,
        )

        if n_parallel <= 1:
            for name in available:
                process_list(config, name)
        else:
            total_workers = config.performance.resolved_num_workers()
            workers_per_list = max(1, total_workers // n_parallel)
            perf = dataclasses.replace(
                config.performance, num_workers=workers_per_list
            )
            derived_config = dataclasses.replace(config, performance=perf)
            logger.info("List parallelism: %d lists x %d workers = %d total processes",
                        n_parallel, workers_per_list, n_parallel * workers_per_list
            )

            with ThreadPoolExecutor(max_workers=n_parallel) as executor:
                futures = {
                    executor.submit(process_list, derived_config, name): name
                    for name in available
                }
                for future in as_completed(futures):
                    future.result()

    else:
        process_list(config, list_name)
