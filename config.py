"""
config.py — Única fonte de verdade para parâmetros do projeto.
Ajuste aqui; o resto do código lê daqui.
"""
from pathlib import Path

# ── Caminhos ──────────────────────────────────────────────────────────────────
ROOT        = Path(__file__).parent
DATA_DIR    = ROOT / "data"
OUTPUT_DIR  = ROOT / "outputs"
OUTPUT_DIR.mkdir(exist_ok=True)

# Arquivo(s) de dados — aceita glob (ex: "*.parquet") ou nome exato
DATA_GLOB   = "*.parquet"          # mude para "*.csv" se necessário

# ── Labels (proxy de aceitação) ───────────────────────────────────────────────
# Trailers que indicam aceitação/revisão positiva (case-insensitive)
ACCEPT_TRAILERS = {"applied", "acked-by", "reviewed-by", "tested-by", "picked-up-by"}

# Score mínimo para considerar patch "aceito" (0–3: trailer=2pts, has_reply=1pt)
ACCEPT_THRESHOLD = 2

# ── Modelo ────────────────────────────────────────────────────────────────────
TEST_SIZE       = 0.2
RANDOM_STATE    = 42
N_ESTIMATORS    = 300
MAX_DEPTH       = 5
LEARNING_RATE   = 0.05

# ── Plots ─────────────────────────────────────────────────────────────────────
PLOT_DPI        = 150
PLOT_STYLE      = "seaborn-v0_8-whitegrid"
TOP_N_AUTHORS   = 20     # autores mais ativos no gráfico
TOP_N_LISTS     = 15     # listas mais ativas
TOP_N_SHAP      = 15     # features no gráfico SHAP
