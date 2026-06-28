"""
eda.py — Análise exploratória do dataset de patches.

Gera gráficos prontos para publicação em outputs/eda_*.png
Cada função é independente e pode ser chamada isoladamente.
"""
import polars as pl
import matplotlib.pyplot as plt
import matplotlib.ticker as mticker
import seaborn as sns
from pathlib import Path

from config import OUTPUT_DIR, PLOT_DPI, PLOT_STYLE, TOP_N_AUTHORS, TOP_N_LISTS

plt.style.use(PLOT_STYLE)
PALETTE = sns.color_palette("muted")


# ── Ponto de entrada ──────────────────────────────────────────────────────────

def run_eda(df: pl.DataFrame) -> None:
    """Executa toda a EDA e salva os gráficos."""
    print("[eda] Gerando análise exploratória...")
    _plot_volume_over_time(df)
    _plot_top_lists(df)
    _plot_top_authors(df)
    _plot_patch_version_dist(df)
    _plot_patchset_size_dist(df)
    _plot_accept_by_list(df)
    _plot_accept_by_version(df)
    _plot_temporal_heatmap(df)
    _print_summary(df)
    print(f"[eda] Gráficos salvos em {OUTPUT_DIR}/")


# ── Gráficos individuais ──────────────────────────────────────────────────────

def _plot_volume_over_time(df: pl.DataFrame) -> None:
    """Volume mensal de patches ao longo do tempo."""
    monthly = (
        df.with_columns(pl.col("date").dt.truncate("1mo").alias("month"))
          .group_by("month")
          .agg(pl.len().alias("count"))
          .sort("month")
    )
    fig, ax = plt.subplots(figsize=(10, 3.5))
    ax.fill_between(monthly["month"].to_list(), monthly["count"].to_list(),
                    alpha=0.3, color=PALETTE[0])
    ax.plot(monthly["month"].to_list(), monthly["count"].to_list(),
            color=PALETTE[0], lw=1.5)
    ax.set_title("Volume mensal de patches", fontsize=13, pad=10)
    ax.set_xlabel("Data"); ax.set_ylabel("Nº de patches")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    _save(fig, "eda_volume_over_time")


def _plot_top_lists(df: pl.DataFrame) -> None:
    """Top N mailing lists por volume."""
    top = (
        df.group_by("list")
          .agg(pl.len().alias("count"))
          .sort("count", descending=True)
          .head(TOP_N_LISTS)
    )
    fig, ax = plt.subplots(figsize=(8, 5))
    sns.barplot(data=top.to_pandas(), x="count", y="list", hue="list",
                palette="Blues_r", legend=False, ax=ax)
    ax.set_title(f"Top {TOP_N_LISTS} mailing lists por volume", fontsize=13, pad=10)
    ax.set_xlabel("Nº de patches"); ax.set_ylabel("")
    ax.xaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    _save(fig, "eda_top_lists")


def _plot_top_authors(df: pl.DataFrame) -> None:
    """Top N autores por número de patches submetidos."""
    top = (
        df.group_by("from")
          .agg(pl.len().alias("count"))
          .sort("count", descending=True)
          .head(TOP_N_AUTHORS)
    )
    fig, ax = plt.subplots(figsize=(8, 6))
    sns.barplot(data=top.to_pandas(), x="count", y="from", hue="from",
                palette="Greens_r", legend=False, ax=ax)
    ax.set_title(f"Top {TOP_N_AUTHORS} autores por volume de patches", fontsize=13, pad=10)
    ax.set_xlabel("Nº de patches"); ax.set_ylabel("")
    _save(fig, "eda_top_authors")


def _plot_patch_version_dist(df: pl.DataFrame) -> None:
    """Distribuição de versões de patch (v1, v2, …)."""
    versions = (
        df.filter(pl.col("has_patch_tag") == True)
          .with_columns(pl.col("patch_version").fill_null(1).clip(upper_bound=10))
          .group_by("patch_version")
          .agg(pl.len().alias("count"))
          .sort("patch_version")
    )
    fig, ax = plt.subplots(figsize=(7, 3.5))
    ax.bar(versions["patch_version"].cast(str).to_list(),
           versions["count"].to_list(), color=PALETTE[2], width=0.6)
    ax.set_title("Distribuição de versões de patch", fontsize=13, pad=10)
    ax.set_xlabel("Versão (vN)"); ax.set_ylabel("Nº de patches")
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda x, _: f"{int(x):,}"))
    _save(fig, "eda_patch_version_dist")


def _plot_patchset_size_dist(df: pl.DataFrame) -> None:
    """Distribuição do tamanho dos patchsets."""
    sizes = (
        df.filter(pl.col("patchset_sequence_number").is_not_null())
          .with_columns(
              pl.col("patchset_sequence_number")
                .str.extract(r"/(\d+)$", 1)
                .cast(pl.Int32, strict=False)
                .alias("size")
          )
          .filter(pl.col("size").is_not_null() & (pl.col("size") <= 50))
          .group_by("size")
          .agg(pl.len().alias("count"))
          .sort("size")
    )
    fig, ax = plt.subplots(figsize=(9, 3.5))
    ax.bar(sizes["size"].to_list(), sizes["count"].to_list(),
           color=PALETTE[1], width=0.7)
    ax.set_title("Distribuição do tamanho dos patchsets", fontsize=13, pad=10)
    ax.set_xlabel("Nº de patches no patchset"); ax.set_ylabel("Frequência")
    _save(fig, "eda_patchset_size_dist")


def _plot_accept_by_list(df: pl.DataFrame) -> None:
    """Taxa de aceitação por mailing list (top N)."""
    top_lists = (
        df.group_by("list").len()
          .sort("len", descending=True)
          .head(TOP_N_LISTS)["list"]
    )
    rates = (
        df.filter(pl.col("list").is_in(top_lists))
          .group_by("list")
          .agg(pl.col("accepted").mean().alias("accept_rate"))
          .sort("accept_rate", descending=True)
    )
    fig, ax = plt.subplots(figsize=(8, 5))
    bars = sns.barplot(data=rates.to_pandas(), x="accept_rate", y="list", hue="list",
                       palette="OrRd_r", legend=False, ax=ax)
    ax.set_title("Taxa de aceitação por mailing list", fontsize=13, pad=10)
    ax.set_xlabel("Taxa de aceitação"); ax.set_ylabel("")
    ax.xaxis.set_major_formatter(mticker.PercentFormatter(xmax=1, decimals=0))
    _save(fig, "eda_accept_by_list")


def _plot_accept_by_version(df: pl.DataFrame) -> None:
    """Taxa de aceitação por versão do patch."""
    rates = (
        df.filter(pl.col("has_patch_tag") == True)
          .with_columns(pl.col("patch_version").fill_null(1).clip(upper_bound=8))
          .group_by("patch_version")
          .agg([
              pl.col("accepted").mean().alias("accept_rate"),
              pl.len().alias("count"),
          ])
          .sort("patch_version")
    )
    fig, ax = plt.subplots(figsize=(7, 3.5))
    ax.plot(rates["patch_version"].cast(str).to_list(),
            rates["accept_rate"].to_list(),
            marker="o", color=PALETTE[3], lw=2, ms=7)
    ax.set_title("Taxa de aceitação por versão do patch", fontsize=13, pad=10)
    ax.set_xlabel("Versão (vN)"); ax.set_ylabel("Taxa de aceitação")
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(xmax=1, decimals=0))
    _save(fig, "eda_accept_by_version")


def _plot_temporal_heatmap(df: pl.DataFrame) -> None:
    """Heatmap: dia da semana × hora do dia (volume de patches)."""
    heat = (
        df.with_columns([
            pl.col("date").dt.hour().alias("hour"),
            pl.col("date").dt.weekday().alias("weekday"),
        ])
        .group_by(["weekday", "hour"])
        .agg(pl.len().alias("count"))
    )
    # Pivot para matriz 7×24
    pivot = (
        heat.to_pandas()
            .pivot(index="weekday", columns="hour", values="count")
            .fillna(0)
    )
    pivot.index = ["Seg", "Ter", "Qua", "Qui", "Sex", "Sáb", "Dom"]
    fig, ax = plt.subplots(figsize=(12, 4))
    sns.heatmap(pivot, cmap="YlOrRd", linewidths=0.3, ax=ax,
                cbar_kws={"label": "Nº de patches"})
    ax.set_title("Volume de patches por dia e hora (UTC)", fontsize=13, pad=10)
    ax.set_xlabel("Hora (UTC)"); ax.set_ylabel("")
    _save(fig, "eda_temporal_heatmap")


def _print_summary(df: pl.DataFrame) -> None:
    """Imprime resumo estatístico para o artigo."""
    print("\n" + "="*55)
    print("  RESUMO DO DATASET")
    print("="*55)
    print(f"  Total de mensagens    : {len(df):>12,}")
    print(f"  Patches identificados : {df['has_patch_tag'].sum():>12,}")
    print(f"  Mailing lists únicas  : {df['list'].n_unique():>12,}")
    print(f"  Autores únicos        : {df['from'].n_unique():>12,}")
    if "accepted" in df.columns:
        n_acc = df["accepted"].sum()
        print(f"  Patches aceitos (proxy): {n_acc:>11,} ({100*n_acc/len(df):.1f}%)")
    date_min = df["date"].min()
    date_max = df["date"].max()
    print(f"  Período               : {date_min} → {date_max}")
    print("="*55 + "\n")


# ── Utilitário ────────────────────────────────────────────────────────────────

def _save(fig: plt.Figure, name: str) -> None:
    path = OUTPUT_DIR / f"{name}.png"
    fig.tight_layout()
    fig.savefig(path, dpi=PLOT_DPI, bbox_inches="tight")
    plt.close(fig)
    print(f"  → {path.name}")
