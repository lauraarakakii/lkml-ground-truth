"""Reproducible fixed analyses implemented with Polars LazyFrames."""

from __future__ import annotations

from collections.abc import Callable

import polars as pl

from ..config import Config
from .datasets import scan_enriched, scan_original

Analysis = Callable[[Config, str], pl.LazyFrame]


def _match_count(column: str) -> pl.Expr:
    return pl.when(pl.col(column).fill_null(False)).then(1).otherwise(0).sum()


def dataset_coverage(config: Config, list_name: str) -> pl.LazyFrame:
    """Compare all source emails with the matching results via a left join."""
    original = scan_original(config, list_name)
    enriched = scan_enriched(config, list_name).select(
        "list",
        "message_id",
        pl.lit(1).alias("_evaluated"),
        "is_match",
        "is_confident_match",
        "error",
    )
    return (
        original.join(
            enriched,
            on=["list", "message_id"],
            how="left",
        )
        .group_by("list")
        .agg(
            pl.len().alias("source_emails"),
            pl.col("_evaluated").count().alias("evaluated_patches"),
            _match_count("is_match").alias("matches"),
            _match_count("is_confident_match").alias("confident_matches"),
            pl.col("error").is_not_null().sum().alias("errors"),
        )
        .sort(["confident_matches", "matches", "list"], descending=[True, True, False])
    )


def match_coverage(config: Config, list_name: str) -> pl.LazyFrame:
    """Summarize candidate coverage and match quality by list."""
    return (
        scan_enriched(config, list_name)
        .group_by("list")
        .agg(
            pl.len().alias("evaluated_patches"),
            _match_count("is_match").alias("matches"),
            _match_count("is_confident_match").alias("confident_matches"),
            pl.col("best_commit").is_null().sum().alias("without_candidate"),
            pl.col("error").is_not_null().sum().alias("errors"),
            pl.col("score").mean().alias("mean_score"),
        )
        .sort(["confident_matches", "matches", "list"], descending=[True, True, False])
    )


def score_bands(config: Config, list_name: str) -> pl.LazyFrame:
    """Group patches by the decision already made by the matcher."""
    band = (
        pl.when(pl.col("is_confident_match").fill_null(False))
        .then(pl.lit("confident_match"))
        .when(pl.col("is_match").fill_null(False))
        .then(pl.lit("review_match"))
        .when(pl.col("best_commit").is_null())
        .then(pl.lit("no_candidate"))
        .otherwise(pl.lit("below_threshold"))
        .alias("result_band")
    )
    return (
        scan_enriched(config, list_name)
        .with_columns(band)
        .group_by("list", "result_band")
        .agg(
            pl.len().alias("patches"),
            pl.col("score").mean().alias("mean_score"),
            pl.col("score").min().alias("min_score"),
            pl.col("score").max().alias("max_score"),
        )
        .sort(["list", "result_band"])
    )


def match_errors(config: Config, list_name: str) -> pl.LazyFrame:
    """Aggregate candidate-search errors for diagnosis."""
    return (
        scan_enriched(config, list_name)
        .filter(pl.col("error").is_not_null())
        .group_by("list", "error")
        .agg(pl.len().alias("occurrences"))
        .sort(["occurrences", "list", "error"], descending=[True, False, False])
    )


def commit_reuse(config: Config, list_name: str) -> pl.LazyFrame:
    """Find commits linked to more than one email in the same list."""
    return (
        scan_enriched(config, list_name)
        .filter(pl.col("is_match").fill_null(False) & pl.col("best_commit").is_not_null())
        .group_by("list", "best_commit")
        .agg(
            pl.col("commit_date").min().alias("commit_date"),
            pl.len().alias("matched_emails"),
            pl.col("score").mean().alias("mean_score"),
        )
        .filter(pl.col("matched_emails") > 1)
        .sort(
            ["matched_emails", "mean_score", "list", "best_commit"],
            descending=[True, True, False, False],
        )
    )


def matched_pairs(config: Config, list_name: str) -> pl.LazyFrame:
    """Return matched email/commit pairs with both dates for review."""
    return (
        scan_enriched(config, list_name)
        .filter(pl.col("is_match").fill_null(False) & pl.col("commit_date").is_not_null())
        .join(
            scan_original(config, list_name).select(
                "list", "message_id", pl.col("date").alias("email_date")
            ),
            on=["list", "message_id"],
            how="inner",
        )
        .select(
            "list",
            "message_id",
            "email_date",
            "commit_date",
            "best_commit",
            "score",
            "is_confident_match",
        )
        .sort(["list", "email_date", "score"], descending=[False, False, True])
    )


ANALYSES: dict[str, Analysis] = {
    "dataset_coverage": dataset_coverage,
    "match_coverage": match_coverage,
    "score_bands": score_bands,
    "match_errors": match_errors,
    "commit_reuse": commit_reuse,
    "matched_pairs": matched_pairs,
}
