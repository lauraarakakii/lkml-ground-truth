"""Índice arquivo -> lista de commits que tocam esse arquivo.

Isto substitui a estratégia antiga de rodar ``git log`` uma vez PRA CADA
patch (o que, com centenas de milhares de patches, significa centenas de
milhares de subprocessos, cada um recomeçando o custo de startup do git
e varrendo o histórico -- é isso que fazia o pipeline levar 20h+ sem
terminar uma lista).

A ideia nova: percorre o histórico do repositório UMA ÚNICA VEZ
(``git log --name-only``), constrói um índice em memória
``{arquivo: [(timestamp, hash), ...]}`` ordenado por tempo, e cacheia em
disco. A busca de candidatos por patch vira uma busca binária em memória
(:mod:`bisect`), sem nenhum subprocess.
"""

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
            commit_hash, ts = line[1:].split(" ")
            current_hash, current_ts = commit_hash, int(ts)
        elif line.strip():
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
        with cache_file.open("rb") as f:
            return pickle.load(f)

    index = build_commit_index(repo_path)

    with cache_file.open("wb") as f:
        pickle.dump(index, f)
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
