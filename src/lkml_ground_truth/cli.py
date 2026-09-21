"""Command-line entry point (``lkml-ground-truth`` / ``python -m lkml_ground_truth``)."""

from __future__ import annotations

import argparse
import dataclasses
from email.policy import default
import logging

from .config import DEFAULT_CONFIG_PATH, load_config
from .enrich import run as run_enrich
from .pipeline import run as run_pipeline
from .query import run as run_query_command
from .repo_setup import ensure_repo

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lkml-ground-truth",
        description=(
            "Match patch emails from a MailingListsHeritage dataset with "
            "commits in the Linux Git repository using PaStA's comparison engine."
        ),
    )
    parser.add_argument(
        "-c",
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help=f"Path to the TOML configuration file (default: {DEFAULT_CONFIG_PATH}).",
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser(
        "run",
        help="Run the full pipeline (the default when no subcommand is given)."
    )

    clone_parser = subparsers.add_parser(
        "clone-repo",
        help=(
            "Clone (or validate) the configured kernel repository at "
            "'paths.repo_path' without running the pipeline."
        ),
    )
    clone_parser.add_argument(
        "--force",
        action="store_true",
        help="Clone even when auto_clone=false in config.toml.",
    )
    subparsers.add_parser( 
        "enrich",
        help="Join the match CSV back into the original dataset by message_id " \
        "and write enriched Parquet data to 'paths.enriched_root'. Run after 'run'."
    )

    query_parser = subparsers.add_parser( 
        "query",
        help="Run Polars SQL queries against the 'original' and 'enriched' "
        "Parquet tables. Without SQL, open an interactive REPL.",
    )

    query_parser.add_argument(
    "sql",
    nargs="?",
    default=None,
    help="SQL query. Tables: 'original' (LKML5Ws dataset) and 'enriched' (matches). "
    "Example: \"SELECT * FROM enriched WHERE is_match=true LIMIT 10\". "
    "Omit to open interactive mode."
    )
    query_parser.add_argument(
        "-l",
        "--list",
        dest="list_name",
        default=None,
        help="List to query (default: 'paths.list_name'). Use 'all' for every list "
        "and add the 'list' column.",
    )
    query_parser.add_argument(
        "--output",
        default=None,
        help="Output file. Without it, results are printed to the terminal."
    )
    query_parser.add_argument(
        "-f",
        "--format",
        dest="fmt",
        choices=("csv", "parquet", "json", "ndjson"),
        default=None,
        help="Export format (default: inferred from --output extension).",
    )
    query_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Maximum terminal rows (0 = all). Does not affect exports. Default: 20.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    config = load_config(args.config)

    command = args.command or "run"

    if command == "clone-repo":
        repo_config = config.repo
        if args.force and not repo_config.auto_clone:
            # An explicit user action overrides only auto_clone. ensure_repo()
            # still skips cloning when repo_path already contains a repository.
            repo_config = dataclasses.replace(repo_config, auto_clone=True)
        ensure_repo(repo_config, config.paths.repo_path)
        return

    if command == "enrich":
        run_enrich(config)
        return

    if command == "query":
        # Without SQL, ``run`` opens a REPL and preserves its SQLContext for
        # subsequent queries. With SQL, it executes only the supplied query.
        run_query_command(
            config,
            args.sql,
            list_name=args.list_name,
            output=args.output,
            fmt=args.fmt,
            limit=args.limit,
        )
        return

    run_pipeline(config)


if __name__ == "__main__":
    main()
