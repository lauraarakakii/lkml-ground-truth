"""
loader.py — Carregamento e validação do dataset.

Suporta três modos:
  1. Pasta raiz com particionamento Hive (list=accel-config/arquivo.parquet)
     → pl.read_parquet com hive_partitioning=True recupera a coluna 'list'
  2. Múltiplos .parquet numa pasta plana → concat com diagonal_relaxed
  3. Arquivo único .parquet ou .csv
"""
import polars as pl
from pathlib import Path
from config import DATA_DIR, DATA_GLOB


REQUIRED_COLS = {
    "message_id", "from", "subject", "date",
    "in_reply_to", "references",
    "has_patch_tag", "patch_version", "patchset_sequence_number",
    "subject_tags", "trailers", "raw_body",
}


def load(path: Path | None = None) -> pl.DataFrame:
    """
    Carrega o dataset. `path` pode ser:
      - Uma pasta raiz com particionamento Hive  (recomendado para o dataset completo)
      - Uma pasta plana com vários .parquet
      - Um arquivo único .parquet / .csv
    Se `path` for None, usa DATA_DIR de config.py.
    """
    root = path or DATA_DIR

    if root.is_dir():
        return _validate(_read_dir(root))

    return _validate(_read_file(root))


# ── Leitura ───────────────────────────────────────────────────────────────────

def _read_dir(root: Path) -> pl.DataFrame:
    """
    Tenta hive_partitioning=True primeiro (recupera 'list' automaticamente).
    Cai para concat manual se não houver subpastas no padrão key=value.
    """
    hive_dirs = [d for d in root.iterdir()
                 if d.is_dir() and "=" in d.name]

    if hive_dirs:
        print(f"[loader] Particionamento Hive detectado — {len(hive_dirs)} partições")
        df = pl.read_parquet(
            root / "**" / "*.parquet",
            hive_partitioning=True,
        )
        return df

    # Pasta plana com vários arquivos
    files = sorted(root.glob(DATA_GLOB))
    if not files:
        raise FileNotFoundError(
            f"Nenhum .parquet encontrado em {root}. "
            "Verifique o caminho ou ajuste DATA_GLOB em config.py."
        )
    print(f"[loader] {len(files)} arquivo(s) encontrado(s) — concatenando...")
    return pl.concat([pl.read_parquet(f) for f in files], how="diagonal_relaxed")


def _read_file(path: Path) -> pl.DataFrame:
    suffix = path.suffix.lower()
    if suffix == ".parquet":
        return pl.read_parquet(path)
    if suffix in {".csv", ".tsv"}:
        return pl.read_csv(path, separator="\t" if suffix == ".tsv" else ",",
                           infer_schema_length=50_000)
    raise ValueError(f"Formato não suportado: {suffix}")


# ── Validação ─────────────────────────────────────────────────────────────────

def _validate(df: pl.DataFrame) -> pl.DataFrame:
    missing = REQUIRED_COLS - set(df.columns)
    if missing:
        raise ValueError(f"Colunas ausentes no dataset: {missing}")

    # 'list' vem do Hive; se ausente, tenta x_mailing_list
    if "list" not in df.columns:
        if "x_mailing_list" in df.columns:
            df = df.with_columns(pl.col("x_mailing_list").alias("list"))
            print("[loader] 'list' ausente — usando 'x_mailing_list'")
        else:
            df = df.with_columns(pl.lit("unknown").alias("list"))
            print("[loader] 'list' ausente — preenchida com 'unknown'")

    if df["date"].dtype == pl.Utf8:
        df = df.with_columns(pl.col("date").str.to_datetime(strict=False))

    if df["patch_version"].dtype in {pl.Float32, pl.Float64}:
        df = df.with_columns(pl.col("patch_version").cast(pl.UInt16, strict=False))

    print(f"[loader] {df.shape[0]:,} mensagens carregadas — {df.shape[1]} colunas")
    return df