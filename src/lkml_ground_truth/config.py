"""Load ``config.toml`` into the typed :class:`Config` model.

This module is the project's single configuration source for paths,
parallelism, and comparison-engine thresholds.
"""

from __future__ import annotations

import logging
import tomllib
import glob
from dataclasses import dataclass
from multiprocessing import cpu_count
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_CONFIG_PATH = "config.toml"


@dataclass(frozen=True)
class Paths:
    """Pipeline input and output paths."""

    repo_path: str
    dataset_root: str
    list_name: str
    output_path: str
    commit_index_cache: str
    enriched_root: str = "output/enriched"

    def parquet_glob(self, list_name: str | None = None) -> str:
        """Glob that reads all ``.parquet`` files for one list."""
        list_name = list_name or self.list_name
        return str(Path(self.dataset_root) / f"list={list_name}" / "*.parquet")

    def resolved_output_path(self, list_name: str | None = None) -> str:
        """Output path with ``{list}`` expanded to the selected list name."""
        list_name = list_name or self.list_name
        return self.output_path.format(list=list_name)

    def enriched_parquet_path(self, list_name: str | None = None) -> str:
        """Path to enriched match Parquet data, ready for analysis."""
        list_name = list_name or self.list_name
        return str(Path(self.enriched_root) / f"list={list_name}" / "data.parquet")    

    def available_lists(self) -> list[str]:
        """Available dataset list names from ``list=<name>`` directories."""
        root = Path(self.dataset_root)
        if not root.is_dir():
            raise FileNotFoundError(
                f"dataset_root does not exist or is not a directory: {root}. "
                "Update paths.dataset_root in config.toml."
            )
        names = (
            p.name.split("=", 1)[1]
            for p in root.iterdir()
            if p.is_dir() and p.name.startswith("list=")
        )
        return sorted(
            name for name in names if name 
        )

    def available_output_lists(self) -> list[str]:
        """List names that already have generated match CSV files."""
        template = self.output_path
        marker = "{list}"
        if marker not in template:
            return []

        prefix, suffix = template.split(marker, 1)
        pattern = f"{prefix}*{suffix}"

        names = []

        for match in glob.glob(pattern):
            if not match.startswith(prefix) or not match.endswith(suffix):
                continue
            name = match[len(prefix): len(match) - len(suffix)] if suffix else match[len(prefix):]
            if name:
                names.append(name)
        return sorted(set(names))
        

@dataclass(frozen=True)
class Performance:
    """File-to-commit index cache and parallelism parameters."""

    num_workers: int
    rebuild_index: bool
    chunksize: int
    progress_every: int
    checkpoint_every: int = 200
    parallel_lists: int =1

    def resolved_num_workers(self) -> int:
        """Worker process count (``0`` = all CPU cores except one)."""
        if self.num_workers and self.num_workers > 0:
            return self.num_workers
        return max(1, cpu_count() - 1)

    def resolved_parallel_lists(self, num_lists: int) -> int:
        """Concurrent list count (``0`` = all CPU cores except one)."""
        if self.parallel_lists == 0:
            n = max(1, min(num_lists, cpu_count() // 4))
        else:
            n = max(1, self.parallel_lists)
        return min(n, num_lists)


DEFAULT_CLONE_URL = "https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git"

_REPO_DEFAULTS = {
    "auto_clone": False,
    "clone_url": DEFAULT_CLONE_URL,
    "since": "",
}


@dataclass(frozen=True)
class RepoConfig:
    """Linux repository automatic-cloning configuration.

    ``auto_clone`` is disabled by default for users with an existing local
    clone. When enabled, the pipeline clones ``repo_path`` before processing.
    ``since`` enables a shallow clone from a date; leave it empty for the
    complete history.
    """

    auto_clone: bool = False
    clone_url: str = DEFAULT_CLONE_URL
    since: str = ""

    def is_shallow(self) -> bool:
        return bool(self.since.strip())


@dataclass(frozen=True)
class Matching:
    """PaStA comparison-engine thresholds and candidate time window."""

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
    """Complete pipeline configuration."""

    paths: Paths
    performance: Performance
    matching: Matching
    repo: RepoConfig


def load_config(path: str | Path = DEFAULT_CONFIG_PATH) -> Config:
    """Read TOML ``path`` and return a validated :class:`Config`."""
    config_path = Path(path)
    if not config_path.exists():
        raise FileNotFoundError(
            f"Configuration file not found: {config_path}. "
            "Copy example_config.toml to config.toml and update its paths."
        )

    with config_path.open("rb") as f:
        raw = tomllib.load(f)

    logger.debug("Loaded configuration from %s", config_path)

    # [repo] is optional so earlier configurations retain manual-clone behavior.
    repo_raw = {**_REPO_DEFAULTS, **raw.get("repo", {})}

    config = Config(
        paths=Paths(**raw["paths"]),
        performance=Performance(**raw["performance"]),
        matching=Matching(**raw["matching"]),
        repo=RepoConfig(**repo_raw),
    )

    if config.performance.chunksize < 1:
        raise ValueError(
            f"performance.chunksize must be >= 1 (received: "
            f"{config.performance.chunksize})."
        )

    if config.performance.progress_every < 1:
        raise ValueError(
            f"performance.progress_every must be >= 1 (received: "
            f"{config.performance.progress_every})."
        )

    return config
