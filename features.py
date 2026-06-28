"""
features.py — Engenharia de features para predição de aceitação de patches.

Todas as features são derivadas de metadados (sem NLP no corpo do email),
tornando o pipeline leve, rápido e reproduzível.

Features geradas
────────────────
  Autor
    author_patch_count      total histórico de patches do autor
    author_accept_rate      taxa de aceitação histórica (leave-one-out implícito)
    author_list_diversity   nº de listas distintas em que o autor contribuiu

  Patch / Patchset
    patch_version           versão do patch (resubmissões têm v > 1)
    is_rfc                  flag RFC no subject
    is_resubmission         patch_version > 1
    patchset_size           tamanho do patchset (extraído de X/N no subject)
    patchset_position       posição dentro do patchset (X de X/N)
    is_cover_letter         posição == 0 (cover letters raramente são aceitas)

  Threading / Atividade
    thread_depth            quantas mensagens nesta thread (via references)
    n_recipients            nº de destinatários (to + cc)
    has_cc                  tem cópia?

  Temporal
    hour_of_day             hora do envio (UTC)
    day_of_week             dia da semana (0=segunda)
    month                   mês do envio

  Lista
    list_encoded            label encoding da mailing list
"""
import polars as pl
import polars.selectors as cs
from config import OUTPUT_DIR


def build_features(df: pl.DataFrame) -> pl.DataFrame:
    """
    Recebe o DataFrame com labels já inferidos.
    Retorna DataFrame com todas as features + colunas de label.
    """
    df = _author_features(df)
    df = _patch_features(df)
    df = _threading_features(df)
    df = _temporal_features(df)
    df = _list_features(df)

    feature_cols = _feature_columns(df)
    print(f"[features] {len(feature_cols)} features geradas")

    # Salva dataset completo (features + labels) para uso posterior
    out = df.select(
        ["message_id", "list", "from", "date", "accepted", "accept_score"]
        + feature_cols
    )
    out.write_parquet(OUTPUT_DIR / "features.parquet")
    print(f"[features] Salvo em outputs/features.parquet ({out.shape[0]:,} linhas)")
    return out


def _author_features(df: pl.DataFrame) -> pl.DataFrame:
    """Reputação do autor com base no histórico dentro do dataset."""
    author_stats = (
        df.group_by("from")
          .agg([
              pl.len().alias("author_patch_count"),
              pl.col("accepted").mean().alias("author_accept_rate"),
              pl.col("list").n_unique().alias("author_list_diversity"),
          ])
    )
    return df.join(author_stats, on="from", how="left")


def _patch_features(df: pl.DataFrame) -> pl.DataFrame:
    """Features derivadas do subject e metadados do patch."""
    return df.with_columns([
        # Versão do patch (null → 0, ou seja, primeira submissão sem marcação)
        pl.col("patch_version").fill_null(0).alias("patch_version"),

        # RFC e resubmissão
        pl.col("has_rfc_tag").cast(pl.Int8).alias("is_rfc"),
        (pl.col("patch_version") > 1).cast(pl.Int8).alias("is_resubmission"),

        # Posição e tamanho do patchset: extrai de strings tipo "3/7" ou "00/12"
        pl.col("patchset_sequence_number")
          .str.extract(r"^(\d+)/", 1)
          .cast(pl.Int32, strict=False)
          .fill_null(0)
          .alias("patchset_position"),

        pl.col("patchset_sequence_number")
          .str.extract(r"/(\d+)$", 1)
          .cast(pl.Int32, strict=False)
          .fill_null(1)
          .alias("patchset_size"),
    ]).with_columns(
        # Cover letter = posição 0 dentro de um patchset
        (pl.col("patchset_position") == 0).cast(pl.Int8).alias("is_cover_letter")
    )


def _threading_features(df: pl.DataFrame) -> pl.DataFrame:
    """Features baseadas em threading e destinatários."""
    # Profundidade da thread = nº de IDs em `references`
    return df.with_columns([
        pl.col("references")
          .list.len()
          .fill_null(0)
          .alias("thread_depth"),

        # Nº total de destinatários (to + cc)
        (
            pl.col("to").list.len().fill_null(0)
            + pl.col("cc").list.len().fill_null(0)
        ).alias("n_recipients"),

        (pl.col("cc").list.len().fill_null(0) > 0)
          .cast(pl.Int8)
          .alias("has_cc"),
    ])


def _temporal_features(df: pl.DataFrame) -> pl.DataFrame:
    """Extrai componentes temporais do campo `date`."""
    return df.with_columns([
        pl.col("date").dt.hour().alias("hour_of_day"),
        pl.col("date").dt.weekday().alias("day_of_week"),
        pl.col("date").dt.month().alias("month"),
    ])


def _list_features(df: pl.DataFrame) -> pl.DataFrame:
    """Label encoding simples para a mailing list."""
    lists = df["list"].unique().sort().to_list()
    list_map = {v: i for i, v in enumerate(lists)}
    return df.with_columns(
        pl.col("list").replace(list_map, return_dtype=pl.Int32).alias("list_encoded")
    )


def _feature_columns(df: pl.DataFrame) -> list[str]:
    """Retorna os nomes das features numéricas geradas (exclui metadados)."""
    exclude = {
        "message_id", "from", "to", "cc", "subject", "raw_body",
        "body_sha1", "_source_reference", "in_reply_to", "references",
        "trailers", "code", "client_date", "subject_tags",
        "untagged_subject", "x_mailing_list", "date", "list",
        "has_response_tag", "has_forward_tag", "has_patch_tag",
        "patchset_sequence_number",
        # labels (não são features)
        "accepted", "accept_score", "has_accept_trailer", "has_reply",
    }
    return [c for c in df.columns if c not in exclude
            and df[c].dtype not in {pl.Utf8, pl.List(pl.Utf8)}]
