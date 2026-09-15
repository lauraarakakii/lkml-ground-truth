"""Leitura tolerante a falhas dos datasets parquet do MailingListsHeritage."""

from __future__ import annotations

import glob as globmod
import logging
import os
from os import PathLike

import polars as pl
import pyarrow.parquet as pq

logger = logging.getLogger(__name__)


def read_parquet_safe(path_or_glob: str | PathLike[str]) -> pl.DataFrame:
    """Lê um parquet único ou múltiplos via glob (ex.: ``pasta/*.parquet``).

    Estratégia principal: Polars, que lê glob nativamente. Fallback: lê
    cada arquivo individualmente, row-group por row-group via PyArrow --
    para datasets grandes/multi-arquivo onde o ``pyarrow.dataset.Scanner``
    trava em colunas aninhadas (bug conhecido com list/struct em múltiplos
    chunks).
    """
    path_or_glob = os.fspath(path_or_glob)

    try:
        return pl.read_parquet(path_or_glob)
    except Exception as exc:
        logger.warning(
            "polars.read_parquet falhou (%s), tentando leitura "
            "row-group por row-group via pyarrow...",
            type(exc).__name__,
        )


    files = (
        sorted(globmod.glob(path_or_glob))
        if any(c in path_or_glob for c in "*?[")
        else [path_or_glob]
    )

    if not files:
        raise FileNotFoundError(
            f"Nenhum arquivo .parquet encontrado para: {path_or_glob!r}. "
            "Verifique 'paths.dataset_root'/nome da lista no config.toml"
        )

    parts = []
    for file in files:
        parquet_file = pq.ParquetFile(file)
        parts.extend(
            pl.from_arrow(parquet_file.read_row_group(i))
            for i in range(parquet_file.num_row_groups)
        )
    return pl.concat(parts, how="vertical_relaxed")
