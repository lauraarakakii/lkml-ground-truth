"""Enrichment: join matching results back into the original dataset."""

from __future__ import annotations

import logging 
from pathlib import Path

import polars as pl

from .config import Config 
from .dataset_io import read_parquet_safe

logger = logging.getLogger(__name__)

MATCH_COLUMNS = ("best_commit", "score", "is_match", "is_confident_match") 
JOIN_KEY = "message_id"

def enrich_list(config: Config, list_name: str) -> None:
    """Write enriched Parquet data for one list (source rows plus match columns)."""
    # glob_path = config.paths.parquet_glob(list_name)
    matches_path = Path(config.paths.resolved_output_path(list_name))
    output_path = Path(config.paths.enriched_parquet_path(list_name))

    # logger.info("=== Enriquecendo lista: %s ===", list_name)

    if not matches_path.exists(): 
        raise FileNotFoundError( 
            f"Match CSV was not found for list '{list_name}': {matches_path}. "
            "Run the pipeline first ('lkml-ground-truth run')."
        )

    # logger.info("Lendo dataset original: %s", glob_path)
    # df = read_parquet_safe(glob_path)

    # logger.info("Lendo matches: %s", matches_path)
    # matches = pl.read_csv(matches_path)

    matches = pl.read_csv(matches_path)
    matched = matches.get_column("best_commit").is_not_null().sum()
    logger.info("-> %d rows in match CSV (%d with a commit)", matches.height, matched)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    # enriched.write_parquet(output_path)
    # logger.info("Dataset enriquecido salvo em %s", output_path)
    matches.write_parquet(output_path)
    logger.info("Parquet salvo em %s", output_path)

def run(config: Config) -> None:
    """Enrichment entry point for one list or every available list."""
    list_name = config.paths.list_name

    if list_name.lower() in ("all", "*"):
        available = config.paths.available_output_lists()
        if not available:
            logger.warning(
                "list_name = '%s', but no match CSVs were found at '%s'. "
                "Run the pipeline first or check paths.output_path in config.toml.",
                list_name,
                config.paths.output_path,
            )
            return
        logger.info("list_name = '%s' -> enriching all %d lists",
                    list_name,
                    len(available),
                    )
        for name in available: 
            enrich_list(config, name)
    else:
        enrich_list(config, list_name)
