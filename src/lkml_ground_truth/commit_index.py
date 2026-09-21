"""Index mapping each file to commits that modify it."""

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
    """Parse ``git log --name-only --format=\\x01%H %ct`` output."""
    index: dict[str, list[tuple[int, str]]] = defaultdict(list)
    current_hash: str | None = None
    current_ts: int | None = None

    for line in text.split("\n"):
        if line.startswith("\x01"):
            parts = line[1:].split(" ", 1)
            if len(parts) != 2 or not parts[0].strip() or not parts[1].strip().isdigit():
                logger.debug("Ignoring unexpected commit header: %r", line)
                continue
            commit_hash, ts = parts[0].strip(), parts[1].strip()
            current_hash, current_ts = commit_hash, int(ts)
        elif line.strip():
            if current_hash is None:
                continue
            index[line.strip()].append((current_ts, current_hash))

    for file_entries in index.values():
        file_entries.sort(key=lambda pair: pair[0])

    return dict(index)


def build_commit_index(repo_path: str) -> CommitIndex:
    """Run ``git log --name-only`` once over the complete repository.

    Return ``{file: [(timestamp, commit_hash), ...]}`` ordered by time.
    """
    logger.info(
        "Building file-to-commit index from %s (one pass; this may take a few "
        "minutes for large histories)...",
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
            f"git log failed while building the index: {result.stderr.strip()}"
        )

    index = _parse_git_log_dump(result.stdout)
    logger.info("Index built: %d distinct files.", len(index))
    return index


def load_or_build_index(
    repo_path: str, cache_path: str, rebuild: bool = False
) -> CommitIndex:
    """Load the index from ``cache_path`` or build and cache it."""
    cache_file = Path(cache_path)

    if not rebuild and cache_file.exists():
        logger.info("Loading index from cache: %s", cache_path)
        try:
            with cache_file.open("rb") as f:
                return pickle.load(f)
        except (pickle.UnpicklingError, 
                EOFError, 
                ValueError, 
                ModuleNotFoundError, 
                AttributeError, 
                ImportError, 
                TypeError) as exc:
            logger.warning(
                "Corrupt index cache (%s); rebuilding: %s",
                cache_path,
                exc,
            )

    index = build_commit_index(repo_path)

    cache_file.parent.mkdir(parents=True, exist_ok=True)
    tmp_file = cache_file.with_suffix(cache_file.suffix + ".tmp")
    with tmp_file.open("wb") as f:
        pickle.dump(index, f)
    tmp_file.replace(cache_file)
    logger.info("Index cached at: %s", cache_path)

    return index


def find_candidates(
    index: CommitIndex, affected_files, since_ts: int, until_ts: int
) -> set[str]:
    """Perform an in-memory binary search without subprocesses.

    Return commits that modify at least one ``affected_files`` entry within
    the ``[since_ts, until_ts]`` time window.
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
