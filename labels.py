"""
labels.py — Inferência de aceitação de patches sem label direto.

Estratégia em duas camadas:
  1. Trailers semânticos (Applied, Acked-by, Reviewed-by…)  → 2 pontos
  2. Threading: patch recebeu pelo menos uma resposta direta → 1 ponto

Score total 0–3, binarizado com ACCEPT_THRESHOLD de config.py.

Nota sobre o schema dos trailers:
  O dataset real usa {"attribution": "<tipo>", "identification": "<pessoa>"},
  ou seja, o TIPO do trailer (Signed-off-by, Applied…) está em `attribution`.
  O código detecta isso automaticamente pelo primeiro campo da struct.
"""
import polars as pl
from config import ACCEPT_TRAILERS, ACCEPT_THRESHOLD


def infer_labels(df: pl.DataFrame) -> pl.DataFrame:
    """
    Adiciona colunas ao DataFrame:
      - `has_accept_trailer`  bool  — tem trailer de aceitação
      - `has_reply`           bool  — alguém respondeu este patch
      - `accept_score`        int   — soma dos pontos (0–3)
      - `accepted`            bool  — label binarizado (score >= threshold)
    """
    df = _add_trailer_label(df)
    df = _add_reply_label(df)

    df = df.with_columns(
        (pl.col("has_accept_trailer").cast(pl.Int8) * 2
         + pl.col("has_reply").cast(pl.Int8)).alias("accept_score")
    )
    df = df.with_columns(
        (pl.col("accept_score") >= ACCEPT_THRESHOLD).alias("accepted")
    )

    n_accepted = df["accepted"].sum()
    pct = 100 * n_accepted / len(df)
    print(f"[labels] {n_accepted:,} patches aceitos ({pct:.1f}%) "
          f"com threshold={ACCEPT_THRESHOLD}")
    return df


# ── Privados ──────────────────────────────────────────────────────────────────

def _trailer_type_field(df: pl.DataFrame) -> str:
    """
    Detecta automaticamente qual campo da struct contém o tipo do trailer
    (ex: "Signed-off-by", "Applied") vs o nome da pessoa.
    Retorna o nome do campo correto.
    """
    trailer_dtype = df.schema["trailers"]
    # List(Struct(...)) → pega os campos da struct interna
    fields = trailer_dtype.inner.fields  # lista de Field(name, dtype)
    field_names = [f.name for f in fields]

    # Heurística: amostra os valores e vê qual campo parece um tipo de trailer
    sample = (
        df.filter(pl.col("trailers").list.len() > 0)
          .head(50)
          .select("trailers")
          .explode("trailers")
    )

    known_types = {"signed-off-by", "acked-by", "reviewed-by", "applied",
                   "tested-by", "reported-by", "fixes", "cc", "link"}

    for field in field_names:
        values = (
            sample.select(pl.col("trailers").struct.field(field))
                  .to_series()
                  .drop_nulls()
                  .str.to_lowercase()
                  .to_list()
        )
        hits = sum(1 for v in values if any(k in v for k in known_types))
        if hits > len(values) * 0.3:   # >30% dos valores batem → é este campo
            print(f"[labels] Campo do tipo de trailer detectado: '{field}'")
            return field

    # Fallback: primeiro campo
    print(f"[labels] Campo do tipo não detectado — usando '{field_names[0]}' como fallback")
    return field_names[0]


def _add_trailer_label(df: pl.DataFrame) -> pl.DataFrame:
    """
    Examina `trailers` (List[Struct]) e marca patches com trailer de aceitação.
    Detecta automaticamente qual campo da struct contém o tipo.
    """
    accept_kw = "|".join(ACCEPT_TRAILERS)
    type_field = _trailer_type_field(df)

    trailer_flags = (
        df.select("message_id", "trailers")
          .explode("trailers")
          .with_columns(
              pl.col("trailers")
                .struct.field(type_field)
                .str.to_lowercase()
                .str.contains(accept_kw)
                .alias("is_accept")
          )
          .group_by("message_id")
          .agg(pl.col("is_accept").any().alias("has_accept_trailer"))
    )

    return df.join(trailer_flags, on="message_id", how="left").with_columns(
        pl.col("has_accept_trailer").fill_null(False)
    )


def _add_reply_label(df: pl.DataFrame) -> pl.DataFrame:
    """
    Um patch "recebeu resposta" se algum outro email tem
    in_reply_to igual ao seu message_id.
    """
    replied_ids = (
        df.filter(pl.col("in_reply_to").is_not_null())
          .select("in_reply_to")
          .unique()
    )
    return df.with_columns(
        pl.col("message_id")
          .is_in(replied_ids["in_reply_to"])
          .alias("has_reply")
    )