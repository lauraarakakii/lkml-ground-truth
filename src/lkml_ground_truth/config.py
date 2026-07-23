"""Carrega ``config.toml`` e o expõe como um objeto tipado (:class:`Config`).

Única fonte de configuração do projeto: caminhos, paralelismo e thresholds
do motor de comparação ficam todos aqui, nunca hardcoded em outros módulos.
"""

from __future__ import annotations

import logging
import tomllib
from dataclasses import dataclass
from multiprocessing import cpu_count
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "config.toml"


@dataclass(frozen=True)
class Paths:
    """Caminhos de entrada/saída do pipeline."""

    repo_path: str
    dataset_root: str
    list_name: str
    output_path: str
    commit_index_cache: str

    def parquet_glob(self, list_name: str | None = None) -> str:
        """Glob para ler todos os ``.parquet`` de uma lista específica."""
        list_name = list_name or self.list_name
        return str(Path(self.dataset_root) / f"list={list_name}" / "*.parquet")

    def resolved_output_path(self, list_name: str | None = None) -> str:
        """Caminho de saída com ``{list}`` substituído pelo nome da lista."""
        list_name = list_name or self.list_name
        return self.output_path.format(list=list_name)

    def available_lists(self) -> list[str]:
        """Nomes de lista disponíveis no dataset (subpastas ``list=<nome>``)."""
        root = Path(self.dataset_root)
        return sorted(
            p.name.split("=", 1)[1]
            for p in root.iterdir()
            if p.is_dir() and p.name.startswith("list=")
        )


@dataclass(frozen=True)
class Performance:
    """Parâmetros de paralelismo e cache do índice arquivo->commits."""

    num_workers: int
    rebuild_index: bool
    chunksize: int
    progress_every: int

    def resolved_num_workers(self) -> int:
        """Número de processos a usar (``0`` = todos os núcleos menos um)."""
        if self.num_workers and self.num_workers > 0:
            return self.num_workers
        return max(1, cpu_count() - 1)


DEFAULT_CLONE_URL = "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git"

_REPO_DEFAULTS = {
    "auto_clone": False,
    "clone_url": DEFAULT_CLONE_URL,
    "since": "",
}


@dataclass(frozen=True)
class RepoConfig:
    """Configuração de clonagem automática do repositório do kernel.

    ``auto_clone`` é opcional e vem desligado por padrão: quem já tem um
    clone local pronto não precisa mexer nesta seção. Quando ligado, o
    pipeline clona ``repo_path`` sozinho antes de rodar.

    ``since`` permite um clone raso a partir de uma data (``--shallow-since``
    do git), o que evita baixar o histórico completo do kernel (décadas,
    dezenas de GB) quando só é preciso casar patches de um período recente.
    Deixe vazio para clonar o histórico inteiro.
    """

    auto_clone: bool = False
    clone_url: str = DEFAULT_CLONE_URL
    since: str = ""

    def is_shallow(self) -> bool:
        return bool(self.since.strip())


@dataclass(frozen=True)
class Matching:
    """Janela de tempo e thresholds do motor de comparação do PaStA."""

    days_before: int
    days_after: int
    autoaccept: float
    interactive: float
    diff_lines_ratio: float
    heading: float
    filename: float
    message_diff_weight: float


@dataclass(frozen=True)
class Config:
    """Configuração completa do pipeline."""

    paths: Paths
    performance: Performance
    matching: Matching
    repo: RepoConfig


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> Config:
    """Lê ``path`` (TOML) e retorna um :class:`Config` validado.

    Levanta ``FileNotFoundError`` com uma mensagem acionável se o arquivo
    não existir (ex.: usuário esqueceu de copiar ``example_config.toml``).
    """
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(
            f"Arquivo de configuração não encontrado: {config_path}. "
            "Copie 'example_config.toml' para 'config.toml' e ajuste os "
            "caminhos para o seu ambiente."
        )

    with config_path.open("rb") as f:
        raw = tomllib.load(f)

    logger.debug("Configuração carregada de %s", config_path)

    # [repo] é opcional: configs antigas, sem essa seção, continuam
    # funcionando com auto_clone desligado (comportamento manual de sempre).
    repo_raw = {**_REPO_DEFAULTS, **raw.get("repo", {})}

    return Config(
        paths=Paths(**raw["paths"]),
        performance=Performance(**raw["performance"]),
        matching=Matching(**raw["matching"]),
        repo=RepoConfig(**repo_raw),
    )
