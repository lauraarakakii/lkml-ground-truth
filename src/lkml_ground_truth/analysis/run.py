"""Command-line runner for fixed Polars analyses."""

from __future__ import annotations

import argparse
from pathlib import Path

from ..config import load_config
from .fixed import ANALYSES


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run a fixed LKML Ground Truth analysis.")
    parser.add_argument("--config", required=True, help="Path to config.toml.")
    parser.add_argument("--analysis", choices=sorted(ANALYSES), required=True)
    parser.add_argument("--list", dest="list_name", default="all", help="List name, or 'all'.")
    parser.add_argument("--output", required=True, help="CSV result path.")
    return parser


def main() -> None:
    args = build_parser().parse_args()
    result = ANALYSES[args.analysis](load_config(args.config), args.list_name).collect()
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    result.write_csv(output)
    print(f"Saved {result.height} row(s) to {output}")


if __name__ == "__main__":
    main()
