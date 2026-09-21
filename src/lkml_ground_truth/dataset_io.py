"""Fault-tolerant readers for MailingListsHeritage Parquet datasets."""

from __future__ import annotations

import glob as globmod
import logging
import os
from os import PathLike

import polars as pl
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)


def read_parquet_safe(path_or_glob: str | PathLike[str]) -> pl.DataFrame:
    """Read one Parquet file or multiple files through a glob pattern.

    Polars is the primary reader. The fallback reads every file and row group
    through PyArrow for datasets that trigger nested-column scanner failures.
    """
    path_or_glob = os.fspath(path_or_glob)

    try:
        return pl.read_parquet(path_or_glob)
    except Exception as exc:
        logger.warning(
            "polars.read_parquet failed (%s); trying PyArrow row-group reads...",
            type(exc).__name__,
        )


    files = (
        sorted(globmod.glob(path_or_glob))
        if any(c in path_or_glob for c in "*?[")
        else [path_or_glob]
    )

    if not files:
        raise FileNotFoundError(
            f"No .parquet files found for: {path_or_glob!r}. "
            "Check paths.dataset_root and the list name in config.toml."
        )

    parts = []
    for file in files:
        parquet_file = pq.ParquetFile(file)
        parts.extend(
            pl.from_arrow(parquet_file.read_row_group(i))
            for i in range(parquet_file.num_row_groups)
        )
    return pl.concat(parts, how="vertical_relaxed")
