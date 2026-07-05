"""Carrega config.toml e expõe como um objeto simples (Config.paths.repo_path etc)."""

import tomllib
from dataclasses import dataclass
from multiprocessing import cpu_count
from pathlib import Path


@dataclass
class Paths:
    repo_path: str
    dataset_root: str
    list_name: str
    output_path: str
    commit_index_cache: str

    def parquet_glob(self, list_name: str = None) -> str:
        """Caminho glob pra ler todos os .parquet de uma lista."""
        list_name = list_name or self.list_name
        return str(Path(self.dataset_root) / f"list={list_name}" / "*.parquet")

    def resolved_output_path(self, list_name: str = None) -> str:
        list_name = list_name or self.list_name
        return self.output_path.format(list=list_name)

    def available_lists(self) -> list:
        """Lista os nomes de lista disponíveis no dataset (baseado nas
        subpastas 'list=<nome>')."""
        root = Path(self.dataset_root)
        return sorted(
            p.name.split("=", 1)[1]
            for p in root.iterdir()
            if p.is_dir() and p.name.startswith("list=")
        )


@dataclass
class Performance:
    num_workers: int
    rebuild_index: bool
    chunksize: int
    progress_every: int

    def resolved_num_workers(self) -> int:
        if self.num_workers and self.num_workers > 0:
            return self.num_workers
        return max(1, cpu_count() - 1)


@dataclass
class Matching:
    days_before: int
    days_after: int
    autoaccept: float
    interactive: float
    diff_lines_ratio: float
    heading: float
    filename: float
    message_diff_weight: float


@dataclass
class Config:
    paths: Paths
    performance: Performance
    matching: Matching


def load_config(path: str = "config.toml") -> Config:
    with open(path, "rb") as f:
        raw = tomllib.load(f)

    return Config(
        paths=Paths(**raw["paths"]),
        performance=Performance(**raw["performance"]),
        matching=Matching(**raw["matching"]),
    )
