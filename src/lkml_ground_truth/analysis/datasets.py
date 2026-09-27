"""Lazy Polars readers for the original and enriched partitioned datasets."""

from __future__ import annotations

from pathlib import Path

import polars as pl

from ..config import Config


def _resolve_lists(root: Path, list_name: str) -> list[str]:
    if list_name.lower() not in {"all", "*"}:
        return [list_name]
    if not root.is_dir():
        raise FileNotFoundError(f"Dataset directory does not exist: {root}")
    return sorted(
        path.name.removeprefix("list=")
        for path in root.iterdir()
        if path.is_dir() and path.name.startswith("list=")
    )


def scan_partitioned_dataset(root: str, list_name: str) -> pl.LazyFrame:
    """Scan requested ``list=<name>`` partitions and add their list name.

    ``diagonal_relaxed`` accommodates columns that are absent from some lists
    or have compatible numeric types without materializing the Parquet data.
    """
    dataset_root = Path(root)
    scans: list[pl.LazyFrame] = []
    for name in _resolve_lists(dataset_root, list_name):
        partition = dataset_root / f"list={name}"
        if not partition.is_dir() or not any(partition.glob("*.parquet")):
            continue
        scans.append(
            pl.scan_parquet(str(partition / "*.parquet"), hive_partitioning=False).with_columns(
                pl.lit(name).alias("list")
            )
        )
    if not scans:
        raise FileNotFoundError(
            f"No Parquet files found in {dataset_root} for list(s): {list_name}."
        )
    return pl.concat(scans, how="diagonal_relaxed")


def scan_original(config: Config, list_name: str) -> pl.LazyFrame:
    """Scan the MLH source dataset."""
    return scan_partitioned_dataset(config.paths.dataset_root, list_name)


def scan_enriched(config: Config, list_name: str) -> pl.LazyFrame:
    """Scan matching results enriched with the list partition name."""
    return scan_partitioned_dataset(config.paths.enriched_root, list_name)
