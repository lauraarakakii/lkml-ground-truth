"""Índice arquivo -> lista de commits que tocam esse arquivo."""

from __future__ import annotations

import logging
import pickle
import subprocess
from bisect import bisect_left, bisect_right
from collections import defaultdict
from pathlib import Path

logger = logging.getLogger(__name__)

CommitIndex = dict[str, list[tuple[int, str]]]


def _parse_git_log_dump(text: str) -> CommitIndex:
    """Converte a saída de ``git log --name-only --format=\\x01%H %ct``."""
    index: dict[str, list[tuple[int, str]]] = defaultdict(list)
    current_hash: str | None = None
    current_ts: int | None = None

    for line in text.split("\n"):
        if line.startswith("\x01"):
            parts = line[1:].split(" ", 1)
            if len(parts) != 2 or not parts[1].strip().isdigit():
                logger.debug("Cabeçalho de commit inesperado ignorado: %r", line)
                continue
            commit_hash, ts = parts[0], parts[1].strip()
            current_hash, current_ts = commit_hash, int(ts)
        elif line.strip():
            if current_hash is None:
                continue
            index[line.strip()].append((current_ts, current_hash))

    for file_entries in index.values():
        file_entries.sort(key=lambda pair: pair[0])

    return dict(index)


def build_commit_index(repo_path: str) -> CommitIndex:
    """Roda ``git log --name-only`` uma vez sobre o repositório inteiro.

    Retorna ``{arquivo: [(timestamp, commit_hash), ...]}`` ordenado por
    tempo.
    """
    logger.info(
        "Construindo índice arquivo->commits a partir de %s "
        "(passada única, pode levar alguns minutos dependendo do tamanho "
        "do histórico)...",
        repo_path,
    )

    result = subprocess.run(
        ["git", "-C", repo_path, "log", "--name-only", "--format=\x01%H %ct"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git log falhou ao construir o índice: {result.stderr.strip()}"
        )

    index = _parse_git_log_dump(result.stdout)
    logger.info("Índice construído: %d arquivos distintos.", len(index))
    return index


def load_or_build_index(
    repo_path: str, cache_path: str, rebuild: bool = False
) -> CommitIndex:
    """Carrega o índice de ``cache_path`` ou o constrói (e cacheia) do zero."""
    cache_file = Path(cache_path)

    if not rebuild and cache_file.exists():
        logger.info("Carregando índice do cache: %s", cache_path)
        try:
            with cache_file.open("rb") as f:
                return pickle.load(f)
        except (pickle.UnpicklingError, EOFError, ValueError) as exc:
            logger.warning(
                "Cache de índice corrompido (%s); reconstruindo: %s",
                cache_path,
                exc,
            )

    index = build_commit_index(repo_path)

    cache_file.parent.mkdir(parent=True, exist_ok=True)
    tmp_file = cache_file.with_suffix(cache_file.suffix + ".tmp")
    with tmp_file.open("wb") as f:
        pickle.dump(index, f)
    tmp_file.replace(cache_file)
    logger.info("Índice salvo em cache: %s", cache_path)

    return index


def find_candidates(
    index: CommitIndex, affected_files, since_ts: int, until_ts: int
) -> set[str]:
    """Busca binária em memória, sem subprocess.

    Retorna o conjunto de hashes de commit que tocam pelo menos um dos
    ``affected_files``, dentro da janela de tempo ``[since_ts, until_ts]``.
    """
    candidates: set[str] = set()
    for file in affected_files:
        entries = index.get(file)
        if not entries:
            continue

        timestamps = [ts for ts, _ in entries]
        lo = bisect_left(timestamps, since_ts)
        hi = bisect_right(timestamps, until_ts)

        for _, commit_hash in entries[lo:hi]:
            candidates.add(commit_hash)

    return candidates
