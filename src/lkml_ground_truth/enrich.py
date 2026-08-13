"""Enriquecimento: junta o resultado do match de volta no dataset original.

O pipeline (:mod: lkml_ground_truth.pipeline) produz um CSV de ground-truth por lista (uma lìnha por e-mail-com-patch). Este módulo faz o passo seguinte, opcional e independente: pega esse CSV e o parquet original do MailinglistsHeritage e escreve um dataset *enriquecido* -- o parquet original acrescido das colunas de match (best commit,score, is match, is_confident_match), unidas por message_id.

É um left join a partir do parquet original: todas as linhas originais são preservadas, inclusive e-mails sem patch (que o pipeline nunca processa) -- essas ficam com as colunas de match nulas. O dataset original e o CSV não são tocados; a saída vai para um dataset novo em paths.enriched root, mantendo o layout list-<nome>/ para ser relido pelas mesmas ferramentas.
"""

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
    """Escreve o parquet enriquecido de uma lista (original + colunas de match).""" 
    glob_path = config.paths.parquet_glob(list_name)
    matches_path = Path(config.paths.resolved_output_path(list_name))
    output_path = Path(config.paths.enriched_parquet_path(list_name))

    logger.info("=== Enriquecendo lista: %s ===", list_name)

    if not matches_path.exists(): 
        raise FileNotFoundError( 
            f"CSV de matches não encontrado para a lista '{list_name}': "
            f"{matches_path}. Rode o pipeline antes ('1kml-ground-truth run')."

    logger.info("Lendo dataset original: %s", glob_path)
    df = read_parquet_safe(glob_path)

    logger.info("Lendo matches: %s", matches_path)
    matches = pl.read_csv(matches_path)

    matches = (
        matches.select(JOIN_KEY, *MATCH_COLUMNS)
        .filter(pl.col(JOIN_KEY).is_not_null() & (pl.col(JOIN_KEY) != ""))
        .unique(subset=JOIN_KEY, keep="first")
    )

    enriched = df.join(matches, on=JOIN_KEY, how="left")
    matched = enriched.get_column("best_commit").is_not_null().sum()
    logger.info("-> %d/%d linhas com commit casado", matched, enriched.height)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    enriched.write_parquet(output_path)
    logger.info("Dataset enriquecido salvo em %s", output_path)

def run(config: Config) -> None:
    """Ponto de entrada do enriquecimento: uma lista ou todas (como o pipeline). """ 
    list_name = config.paths.list_name

    if list_name.lower() in ("all", "*", "todas"):
        available = config.paths.available_lists()
        logger.info("list_name = '%s' -> enriquecendo TODAS as %d listas",
                    list_name,
                    len(available),
                    )
        for name in available: 
            enrich_list(config, name)
    else:
        enrich_list(config, list_name)