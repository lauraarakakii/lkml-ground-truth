from __future__ import annotations

import argparse
from pathlib import Path

from ..config import load_config
from .query import run


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Query the LKML Ground Truth original and enriched datasets."
    )
    parser.add_argument(
        "-c",
        "--config",
        default=str(Path(__file__).resolve().parents[3] / "config.toml"),
        help="Path to config.toml (default: the repository config.toml).",
    )
    parser.add_argument("sql", nargs="?", help="SQL to execute; omit for the interactive REPL.")
    parser.add_argument("-l", "--list", dest="list_name", help="List name, or 'all'.")
    parser.add_argument("--output", help="Optional result path (CSV, Parquet, JSON, or NDJSON).")
    parser.add_argument(
        "-f",
        "--format",
        dest="fmt",
        choices=("csv", "parquet", "json", "ndjson"),
        help="Output format; inferred from --output when omitted.",
    )
    parser.add_argument("--limit", type=int, default=20, help="Terminal row limit; 0 shows all.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    run(
        load_config(args.config),
        args.sql,
        list_name=args.list_name,
        output=args.output,
        fmt=args.fmt,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
