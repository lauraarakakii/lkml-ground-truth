import polars as pl

from lkml_ground_truth.analysis import fixed


def test_dataset_coverage_joins_original_and_enriched(monkeypatch):
    original = pl.DataFrame(
        {
            "list": ["netdev", "netdev", "iio"],
            "message_id": ["a", "b", "c"],
        }
    ).lazy()
    enriched = pl.DataFrame(
        {
            "list": ["netdev", "iio"],
            "message_id": ["a", "c"],
            "is_match": [True, False],
            "is_confident_match": [True, False],
            "error": [None, "candidate_search: bad date"],
        }
    ).lazy()
    monkeypatch.setattr(fixed, "scan_original", lambda *args: original)
    monkeypatch.setattr(fixed, "scan_enriched", lambda *args: enriched)

    result = fixed.dataset_coverage(object(), "all").collect().sort("list")

    assert result.to_dicts() == [
        {
            "list": "iio",
            "source_emails": 1,
            "evaluated_patches": 1,
            "matches": 0,
            "confident_matches": 0,
            "errors": 1,
        },
        {
            "list": "netdev",
            "source_emails": 2,
            "evaluated_patches": 1,
            "matches": 1,
            "confident_matches": 1,
            "errors": 0,
        },
    ]
