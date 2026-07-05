"""
Índice arquivo -> lista de commits que tocam esse arquivo.

Isto substitui a estratégia antiga de rodar `git log` uma vez PRA CADA
patch (o que, com centenas de milhares de patches, significa centenas de
milhares de subprocessos, cada um recomeçando o custo de startup do git
e varrendo o histórico -- é isso que fazia o pipeline levar 20h+ sem
terminar uma lista).

A ideia nova: percorre o histórico do repositório UMA ÚNICA VEZ (`git log
--name-only`), constrói um índice em memória {arquivo: [(timestamp, hash), ...]}
ordenado por tempo, e cacheia em disco. A busca de candidatos por patch
vira uma busca binária em memória (bisect), sem nenhum subprocess.
"""

import pickle
import subprocess
from bisect import bisect_left, bisect_right
from collections import defaultdict
from pathlib import Path


def _parse_git_log_dump(text: str) -> dict:
    index = defaultdict(list)
    current_hash = None
    current_ts = None

    for line in text.split("\n"):
        if line.startswith("\x01"):
            commit_hash, ts = line[1:].split(" ")
            current_hash, current_ts = commit_hash, int(ts)
        elif line.strip():
            index[line.strip()].append((current_ts, current_hash))

    for file in index:
        index[file].sort(key=lambda pair: pair[0])

    return dict(index)


def build_commit_index(repo_path: str) -> dict:
    """Roda `git log --name-only` UMA VEZ sobre o repositório inteiro e
    devolve {arquivo: [(timestamp, commit_hash), ...]} ordenado por tempo."""

    print(f"  Construindo índice arquivo->commits a partir de {repo_path} "
          f"(passada única, pode levar alguns minutos dependendo do tamanho "
          f"do histórico)...")

    result = subprocess.run(
        ["git", "-C", repo_path, "log", "--name-only", "--format=\x01%H %ct"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"git log falhou ao construir o índice: {result.stderr.strip()}"
        )

    index = _parse_git_log_dump(result.stdout)
    print(f"  Índice construído: {len(index)} arquivos distintos.")
    return index


def load_or_build_index(repo_path: str, cache_path: str, rebuild: bool = False) -> dict:
    cache_file = Path(cache_path)

    if not rebuild and cache_file.exists():
        print(f"  Carregando índice do cache: {cache_path}")
        with open(cache_file, "rb") as f:
            return pickle.load(f)

    index = build_commit_index(repo_path)

    with open(cache_file, "wb") as f:
        pickle.dump(index, f)
    print(f"  Índice salvo em cache: {cache_path}")

    return index


def find_candidates(index: dict, affected_files, since_ts: int, until_ts: int) -> set:
    """Busca binária em memória, sem subprocess. Retorna set de commit hashes
    que tocam pelo menos um dos arquivos afetados, dentro da janela de tempo."""

    candidates = set()
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
