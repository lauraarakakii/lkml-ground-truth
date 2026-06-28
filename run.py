"""
run.py — Ponto de entrada único do pipeline.

Uso:
    python run.py                  # pipeline completo
    python run.py --only eda       # só EDA
    python run.py --only features  # só feature engineering
    python run.py --only model     # só modelo (requer features.parquet)
    python run.py --data meu_arquivo.parquet
"""
import argparse
import time
from pathlib import Path

from loader import load
from labels import infer_labels
from features import build_features
from eda import run_eda
from model import run_model


def main(only: str | None = None, data_path: Path | None = None) -> None:
    t0 = time.time()

    run_eda_flag      = only in {None, "eda"}
    run_features_flag = only in {None, "features", "model"}
    run_model_flag    = only in {None, "model"}

    # ── Carga ──────────────────────────────────────────────────────────────
    print("\n── CARGA DE DADOS ───────────────────────────────────────")
    df = load(data_path)

    # ── Labels ─────────────────────────────────────────────────────────────
    print("\n── INFERÊNCIA DE LABELS ─────────────────────────────────")
    df = infer_labels(df)

    # ── EDA ────────────────────────────────────────────────────────────────
    if run_eda_flag:
        print("\n── ANÁLISE EXPLORATÓRIA ─────────────────────────────────")
        run_eda(df)

    # ── Feature engineering ────────────────────────────────────────────────
    if run_features_flag:
        print("\n── FEATURE ENGINEERING ──────────────────────────────────")
        feat_df = build_features(df)

    # ── Modelo ─────────────────────────────────────────────────────────────
    if run_model_flag:
        print("\n── TREINAMENTO E AVALIAÇÃO ──────────────────────────────")
        run_model()

    elapsed = time.time() - t0
    print(f"\n✓ Pipeline concluído em {elapsed:.1f}s")
    print(f"  Resultados em: outputs/\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Pipeline de análise de patches")
    parser.add_argument(
        "--only",
        choices=["eda", "features", "model"],
        default=None,
        help="Executa apenas uma etapa do pipeline",
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=None,
        help="Caminho explícito para o arquivo de dados",
    )
    args = parser.parse_args()
    main(only=args.only, data_path=args.data)
