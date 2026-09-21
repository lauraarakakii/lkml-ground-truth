"""Patch-to-commit comparison core, isolated from pipeline orchestration."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from .commit_index import CommitIndex, find_candidates, load_or_build_index
from .config import Config
from .pasta.patch_evaluation import evaluate_patch_pair
from .pasta.repository.message_diff import MessageDiff, Signature
from .pasta.repository.patch import Diff
from .pasta.repository.repository import Repository

logger = logging.getLogger(__name__)


class Thresholds:
    """Subset of ``pypasta.Config.py`` required by the comparison engine."""

    def __init__(
        self,
        autoaccept: float,
        interactive: float,
        diff_lines_ratio: float,
        heading: float,
        filename: float,
        message_diff_weight: float,
    ) -> None:
        self.autoaccept = autoaccept
        self.interactive = interactive
        self.heading = heading
        self.filename = filename
        self.message_diff_weight = message_diff_weight
        self.diff_lines_ratio = diff_lines_ratio
        self.author_date_interval = 0  # Not used by this pipeline.


def thresholds_from_config(config: Config) -> Thresholds:
    """Build :class:`Thresholds` from the ``[matching]`` section."""
    return Thresholds(
        autoaccept=config.matching.autoaccept,
        interactive=config.matching.interactive,
        diff_lines_ratio=config.matching.diff_lines_ratio,
        heading=config.matching.heading,
        filename=config.matching.filename,
        message_diff_weight=config.matching.message_diff_weight,
    )


# ---------------------------------------------------------------------------
# Process-global state is initialized before the pool. Linux fork workers
# inherit it through copy-on-write, avoiding repeated serialization.
# ---------------------------------------------------------------------------

_repo: Repository | None = None
_index: CommitIndex | None = None
_config: Config | None = None
_thresholds: Thresholds | None = None


def init_worker_globals(config: Config) -> None:
    """Open the repository and load or build the index in the main process."""
    global _repo, _index, _config, _thresholds
    _config = config
    _thresholds = thresholds_from_config(config)
    _repo = Repository("linux", config.paths.repo_path)
    _index = load_or_build_index(
        config.paths.repo_path,
        config.paths.commit_index_cache,
        rebuild=config.performance.rebuild_index,
    )


def row_to_messagediff(row: dict[str, Any]) -> MessageDiff | None:
    """Convert a dataset row into a PaStA :class:`MessageDiff`.

    Return ``None`` when a row has no usable or parseable diff.
    """
    code = row.get("code")
    if code is None or len(code) == 0:
        return None

    diff_text = "\n".join(code)
    diff_lines = diff_text.split("\n")

    try:
        parsed_diff = Diff(diff_lines)
    except Exception:
        logger.debug("Could not parse diff for %s", row.get("message_id"))
        return None

    if not parsed_diff.affected:
        return None

    message_text = row.get("untagged_subject") or ""
    body = row.get("raw_body") or ""
    if diff_text and diff_text in body:
        body = body.split(diff_text)[0]
    message_lines = [message_text, *body.split("\n")]

    author_str = row.get("from") or "unknown <unknown@example.com>"
    if "<" in author_str and ">" in author_str:
        name = author_str.split("<")[0].strip().strip('"')
        email = author_str.split("<")[1].split(">")[0].strip()
    else:
        name, email = author_str, "unknown@example.com"

    message_id = row.get("message_id")
    if not message_id:
        return None

    author = Signature(name, email, row.get("date"))
    content = (message_lines, None, diff_lines)

    message_diff = MessageDiff.__new__(MessageDiff)
    MessageDiff.__init__(message_diff, message_id, content, author)
    return message_diff


def process_row(row: dict[str, Any]) -> dict[str, Any] | None:
    """Match a dataset patch-email row with the best candidate commit."""
    assert _config is not None and _thresholds is not None and _repo is not None
    assert _index is not None

    message_diff = row_to_messagediff(row)
    if message_diff is None:
        return None

    try:
        date = row["date"]
        since_ts = int((date - timedelta(days=_config.matching.days_before)).timestamp())
        until_ts = int((date + timedelta(days=_config.matching.days_after)).timestamp())
        candidates = find_candidates(_index, message_diff.diff.affected, since_ts, until_ts)
    except Exception as exc:  
        return {
            "message_id": row.get("message_id"),
            "best_commit": None,
            "score": None,
            "is_match": False,
            "is_confident_match": False,
            "error": f"candidate_search: {exc}",
        }

    best_score: float | None = None
    best_hash: str | None = None

    for commit_hash in candidates:
        try:
            commit = _repo[commit_hash]
        except Exception:
            continue

        sim = evaluate_patch_pair(
            _thresholds,
            (" ".join(message_diff.message), message_diff.diff),
            (" ".join(commit.message), commit.diff),
        )
        score = (
            _thresholds.message_diff_weight * sim.msg
            + (1 - _thresholds.message_diff_weight) * sim.diff
        )
        if (best_score is None 
            or score > best_score
            or (score == best_score and (best_hash is None or commit_hash < best_hash))
        ):
            best_score, best_hash = score, commit_hash

    return {
        "message_id": row.get("message_id"),
        "best_commit": best_hash,
        "score": best_score,
        "is_match": best_score is not None and best_score >= _thresholds.interactive,
        "is_confident_match": best_score is not None and best_score >= _thresholds.autoaccept,
        "error": None,
    }
