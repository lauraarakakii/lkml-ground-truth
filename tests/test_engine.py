from datetime import UTC, datetime
from types import SimpleNamespace

import lkml_ground_truth.engine as engine


def test_process_row_includes_selected_commit_committer_date(monkeypatch):
    """The exported date belongs to the same commit selected as the best match."""
    commit_date = datetime(2026, 9, 27, 10, 30, tzinfo=UTC)
    message_diff = SimpleNamespace(message=["subject"], diff=SimpleNamespace(affected=[]))
    commit = SimpleNamespace(
        message=["subject"],
        diff=SimpleNamespace(),
        committer=SimpleNamespace(date=commit_date),
    )

    monkeypatch.setattr(
        engine,
        "_config",
        SimpleNamespace(matching=SimpleNamespace(days_before=3, days_after=365)),
    )
    monkeypatch.setattr(
        engine,
        "_thresholds",
        SimpleNamespace(interactive=0.5, autoaccept=0.8, message_diff_weight=0.5),
    )
    monkeypatch.setattr(engine, "_repo", {"abcdef": commit})
    monkeypatch.setattr(engine, "_index", {})
    monkeypatch.setattr(engine, "row_to_messagediff", lambda row: message_diff)
    monkeypatch.setattr(engine, "find_candidates", lambda *args: {"abcdef"})
    monkeypatch.setattr(
        engine, "evaluate_patch_pair", lambda *args: SimpleNamespace(msg=1.0, diff=1.0)
    )

    result = engine.process_row(
        {"message_id": "message@example.com", "date": commit_date}
    )

    assert result["best_commit"] == "abcdef"
    assert result["commit_date"] == "2026-09-27T10:30:00+00:00"
