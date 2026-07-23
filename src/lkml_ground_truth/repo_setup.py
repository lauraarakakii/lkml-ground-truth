"""Clonagem opcional do repositório git do Linux.

Por padrão o usuário providencia o clone manualmente (``auto_clone =
false``, o padrão) e só aponta ``repo_path`` para ele em ``config.toml``.
Quando ``auto_clone = true``, :func:`ensure_repo` cuida disso sozinho
antes do pipeline rodar -- inclusive com a opção de um clone raso
(``since``) para não precisar baixar décadas de histórico quando só é
preciso casar patches de um período recente.
"""

from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from .config import RepoConfig

logger = logging.getLogger(__name__)


def _looks_like_git_repo(path: Path) -> bool:
    """``True`` se ``path`` já é um clone git (normal ou bare)."""
    if (path / ".git").exists():
        return True
    # repositório bare (ex.: mirror sem working tree)
    return (path / "HEAD").exists() and (path / "objects").is_dir()


def ensure_repo(repo_config: RepoConfig, repo_path: str) -> None:
    """Garante que ``repo_path`` seja um clone git válido antes do pipeline rodar.

    - Se já existe um repositório em ``repo_path``, não faz nada.
    - Se não existe e ``auto_clone`` está desligado, levanta um erro
      explicando como cloná-lo manualmente ou ligar o auto-clone.
    - Se não existe e ``auto_clone`` está ligado, clona (raso, a partir de
      ``repo_config.since``, ou completo).
    """
    path = Path(repo_path)

    if _looks_like_git_repo(path):
        logger.info("Repositório git já existe em %s, pulando clone.", repo_path)
        return

    if path.exists() and any(path.iterdir()):
        raise FileNotFoundError(
            f"'{repo_path}' existe mas não parece um clone git válido "
            "(sem .git/objects). Aponte 'paths.repo_path' para um clone "
            "existente, ou para um diretório vazio/inexistente para deixar "
            "o auto-clone criar."
        )

    if not repo_config.auto_clone:
        example_cmd = f"git clone {repo_config.clone_url} {repo_path}"
        raise FileNotFoundError(
            f"Repositório git não encontrado em '{repo_path}'.\n"
            f"  - Clone manualmente:  {example_cmd}\n"
            "  - Ou habilite o auto-clone em config.toml:\n"
            "        [repo]\n"
            "        auto_clone = true\n"
            "        # since = \"2015-01-01\"  # opcional: só esse período em diante"
        )

    clone_repo(repo_config, repo_path)


def clone_repo(repo_config: RepoConfig, repo_path: str) -> None:
    """Clona ``repo_config.clone_url`` em ``repo_path``.

    Faz um clone raso (``--shallow-since``) se ``repo_config.since`` estiver
    preenchido, ou um clone completo caso contrário.
    """
    path = Path(repo_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    cmd = ["git", "clone", "--progress"]

    if repo_config.is_shallow():
        logger.info(
            "Clonando %s em %s (apenas histórico a partir de %s -- clone "
            "raso, bem mais rápido e leve que o histórico completo)...",
            repo_config.clone_url,
            repo_path,
            repo_config.since,
        )
        cmd.append(f"--shallow-since={repo_config.since}")
    else:
        logger.info(
            "Clonando %s em %s (histórico completo -- isso baixa dezenas "
            "de GB e pode levar bastante tempo; defina 'repo.since' em "
            "config.toml se só precisar de um período recente)...",
            repo_config.clone_url,
            repo_path,
        )

    cmd += [repo_config.clone_url, str(path)]

    # git manda o progresso em stderr; deixa passar direto pro terminal
    # do usuário em vez de capturar (clone pode levar minutos/horas).
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"'git clone' falhou (exit code {result.returncode}) ao clonar "
            f"{repo_config.clone_url} em {repo_path}."
        )

    logger.info("Clone concluído em %s.", repo_path)
