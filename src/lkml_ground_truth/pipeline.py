"""Orquestração do pipeline: uma lista (ou todas) do dataset -> CSV de matches.

Este módulo só cuida de I/O e do ``multiprocessing.Pool``; a lógica de
comparação patch<->commit vive em :mod:`lkml_ground_truth.engine`.
"""

from __future__ import annotations

import logging
from multiprocessing import Pool
from pathlib import Path

import polars as pl

from .config import Config
from .dataset_io import read_parquet_safe
from .engine import init_worker_globals, process_row
from .repo_setup import ensure_repo

logger = logging.getLogger(__name__)

def _checkpoint_path(output_path: str) -> Path:
    return Path(output_path).with_suffix(".ckpt")

def _load_checkpoint(output_path: str) -> tuple[list[dict], set[str]]:
    """Carrega checkpoint (se existir) e retorna resultados + índice de continuação."""
    ckpt = _checkpoint_path(output_path)
    if not ckpt.exists():
        return [], set()
    try:
        logger.info("Checkpoint encontrado: %s -> carregando...", ckpt)
        df = pl.read_csv(ckpt, schema_overrides=_RESULT_SCHEMA)
        rows = df.to_dicts()
        ids = {r["message_id"] for r in rows if r.get("message_id")}
        logger.info(
            "Checkpoint encontrado: %d linhas já processadas (%s) - retomando.",
            len(rows),
            ckpt,
        )
        return rows, ids
    except Exception as exc:
        logger.warning(
            "Falha ao carregar checkpoint (%s): %s. Começando do zero.", ckpt, exc
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
    """Processa uma lista específica do dataset (uma subpasta ``list=<nome>``)."""
    glob_path = config.paths.parquet_glob(list_name)
    output_path = config.paths.resolved_output_path(list_name)

    logger.info("=== Lista: %s ===", list_name)
    logger.info("Carregando dataset: %s", glob_path)
    df = read_parquet_safe(glob_path)
    df_patches = df.filter(pl.col("code").is_not_null())
    logger.info("-> %d e-mails com diff (de %d totais)", df_patches.height, df.height)

    prior_results, done_ids = _load_checkpoint(output_path)
    if done_ids:
        df_patches = df_patches.filter(~pl.col("message_id").is_in(done_ids))
        logger.info(
            "-> %d e-mails restantes após checkpoint (de %d totais)",
            df_patches.height,
            df.height
        )

    if df_patches.height == 0 and not prior_results:
        logger.info("Nada pra processar nessa lista.")
        return

    ckpt = _checkpoint_path(output_path)
    results: list[dict] = prior_results

    if df_patches.height > 0:
        num_workers = config.performance.resolved_num_workers()
    logger.info(
        "Processando com %d processo(s) em paralelo "
        "(ajuste em config.toml -> [performance] -> num_workers)...",
        num_workers,
    )

    checkpoint_every = config.performance.checkpoint_every
    batch: list[dict] = []
    rows_iter = df_patches.iter_rows(named=True)

    with Pool(num_workers, initializer=_open_worker_repo) as pool:
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
                    "Checkpoint salvo (%d linhas) em %s", len(batch), ckpt
                )
                batch.clear()
            if i % config.performance.progress_every == 0 or i == df_patches.height:
                logger.info("processado %d/%d...", i, df_patches.height)

    if batch and checkpoint_every > 0:
        _append_checkpoint(ckpt, batch)
        logger.info(
            "Checkpoint final salvo (%d linhas) em %s", len(batch), ckpt
        )

    Path(output_path).parent.mkdir(parents=True, exist_ok=True)

    if not results:
        logger.info("Nenhum resultado (nenhuma linha tinha diff utilizável).")
        return
    else:
        out = pl.DataFrame(results, infer_schema_length=None)
        out.write_csv(output_path)
        logger.info("Pronto. Resultados salvos em %s", output_path)
        logger.info("%s", out.group_by("is_match").len())
        n_errors = out.filter(pl.col("error").is_not_null()).height
        if n_errors:
            logger.warning("%d linhas tiveram erro (ver coluna 'error' no CSV).", n_errors)

    if ckpt.exists():
        ckpt.unlink()
        logger.debbug("Checkpoint removido: %s", ckpt)

def run(config: Config) -> None:
    """Ponto de entrada do pipeline: garante o repo, abre-o e processa a(s) lista(s)."""
    ensure_repo(config.repo, config.paths.repo_path)

    logger.info(
        "Abrindo repositório e construindo/carregando índice: %s", config.paths.repo_path
    )
    init_worker_globals(config)  

    list_name = config.paths.list_name

    if list_name.lower() in ("all", "*", "todas"):
        available = config.paths.available_lists()
        logger.info(
            "list_name = '%s' -> processando TODAS as %d listas encontradas em %s",
            list_name,
            len(available),
            config.paths.dataset_root,
        )
        for name in available:
            process_list(config, name)
    else:
        process_list(config, list_name)
