"""Optional cloning for the Linux Git repository."""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .config import RepoConfig

logger = logging.getLogger(__name__)


def _looks_like_git_repo(path: Path) -> bool:
    """Return whether ``path`` is a regular or bare Git clone."""
    if (path / ".git").exists():
        return True
    # Bare repository, such as a mirror without a working tree.
    return (path / "HEAD").exists() and (path / "objects").is_dir()


def ensure_repo(repo_config: RepoConfig, repo_path: str) -> None:
    """Ensure ``repo_path`` contains a valid Git clone before processing."""
    path = Path(repo_path)

    if _looks_like_git_repo(path):
        logger.info("Git repository already exists at %s; skipping clone.", repo_path)
        return

    if path.exists() and not path.is_dir():
        raise FileNotFoundError(
            f"'{repo_path}' exists but is not a directory. Set paths.repo_path "
            "to an existing Git clone or an empty/nonexistent directory for auto-clone."
        )

    if path.is_dir() and any(path.iterdir()):
        raise FileNotFoundError(
            f"'{repo_path}' exists but does not look like a valid Git clone "
            "(missing .git/objects). Set paths.repo_path to an existing clone "
            "or an empty/nonexistent directory for auto-clone."
        )

    if not repo_config.auto_clone:
        example_cmd = f"git clone {repo_config.clone_url} {repo_path}"
        raise FileNotFoundError(
            f"Git repository not found at '{repo_path}'.\n"
            f"  - Clone it manually:  {example_cmd}\n"
            "  - Or enable auto-clone in config.toml:\n"
            "        [repo]\n"
            "        auto_clone = true\n"
            "        # since = \"2015-01-01\"  # optional lower history bound"
        )

    clone_repo(repo_config, repo_path)


def clone_repo(repo_config: RepoConfig, repo_path: str) -> None:
    """Clone ``repo_config.clone_url`` into ``repo_path``."""
    path = Path(repo_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["git", "clone", "--progress"]

    if repo_config.is_shallow():
        logger.info(
            "Cloning %s into %s (history since %s; shallow clone)...",
            repo_config.clone_url,
            repo_path,
            repo_config.since,
        )
        cmd.append(f"--shallow-since={repo_config.since}")
    else:
        logger.info(
            "Cloning %s into %s (complete history; this can download tens of GB). "
            "Set repo.since in config.toml if only recent history is needed...",
            repo_config.clone_url,
            repo_path,
        )

    cmd += [repo_config.clone_url, str(path)]

    # Git writes progress to stderr; preserve it in the user's terminal.
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"'git clone' failed (exit code {result.returncode}) while cloning "
            f"{repo_config.clone_url} into {repo_path}."
        )

    logger.info("Clone completed at %s.", repo_path)
