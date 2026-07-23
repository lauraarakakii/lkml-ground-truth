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


def process_list(config: Config, list_name: str) -> None:
    """Processa uma lista específica do dataset (uma subpasta ``list=<nome>``)."""
    glob_path = config.paths.parquet_glob(list_name)
    output_path = config.paths.resolved_output_path(list_name)

    logger.info("=== Lista: %s ===", list_name)
    logger.info("Carregando dataset: %s", glob_path)
    df = read_parquet_safe(glob_path)
    df_patches = df.filter(pl.col("code").is_not_null())
    logger.info("-> %d e-mails com diff (de %d totais)", df_patches.height, df.height)

    if df_patches.height == 0:
        logger.info("Nada pra processar nessa lista.")
        return

    num_workers = config.performance.resolved_num_workers()
    logger.info(
        "Processando com %d processo(s) em paralelo "
        "(ajuste em config.toml -> [performance] -> num_workers)...",
        num_workers,
    )

    rows_iter = df_patches.iter_rows(named=True)

    results = []
    with Pool(num_workers) as pool:
        for i, result in enumerate(
            pool.imap_unordered(process_row, rows_iter, chunksize=config.performance.chunksize)
        ):
            if result is not None:
                results.append(result)
            if i % config.performance.progress_every == 0:
                logger.info("processado %d/%d...", i, df_patches.height)

    if not results:
        logger.info("Nenhum resultado (nenhuma linha tinha diff utilizável).")
        return

    out = pl.DataFrame(results)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    out.write_csv(output_path)

    logger.info("Pronto. Resultados salvos em %s", output_path)
    logger.info("%s", out.group_by("is_match").len())

    n_errors = out.filter(pl.col("error").is_not_null()).height
    if n_errors:
        logger.warning("%d linhas tiveram erro (ver coluna 'error' no CSV).", n_errors)


def run(config: Config) -> None:
    """Ponto de entrada do pipeline: garante o repo, abre-o e processa a(s) lista(s)."""
    ensure_repo(config.repo, config.paths.repo_path)

    logger.info(
        "Abrindo repositório e construindo/carregando índice: %s", config.paths.repo_path
    )
    init_worker_globals(config)  # roda no processo principal ANTES do Pool (fork)

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
