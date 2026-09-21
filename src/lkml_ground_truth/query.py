from __future__ import annotations

import logging
import re
import time
from collections.abc import Collection
from pathlib import Path

import polars as pl

try:
    import readline  
except ImportError:
    pass

from .config import Config
from .dataset_io import read_parquet_safe

logger = logging.getLogger(__name__)

ORIGINAL_TABLE = "original"
ENRICHED_TABLE = "enriched"
JOIN_KEY = "message_id"
LIST_COLUMN = "list"

_KNOWN_TABLES = frozenset((ORIGINAL_TABLE, ENRICHED_TABLE))
_TABLE_REFERENCE = re.compile(
    r"\b(?:from|join)\s+[`\"]?(original|enriched)[`\"]?\b", re.IGNORECASE
)

_ALL_ALIASES = ("all", "*")
_EXIT_COMMANDS = ("exit", "quit", r"\q")

_EXPORTERS = {
    "csv": lambda df, path: df.write_csv(path),
    "parquet": lambda df, path: df.write_parquet(path),
    "json": lambda df, path: df.write_json(path),
    "ndjson": lambda df, path: df.write_ndjson(path),
}

_EXTENSION_FORMATS = {
    ".csv": "csv",
    ".parquet": "parquet",
    ".json": "json",
    ".ndjson": "ndjson",
}

def _available_enriched_lists(config: Config) -> list[str]:
    """List names available in enriched ``list=<name>`` directories."""
    root = Path(config.paths.enriched_root)
    if not root.is_dir():
        return []
    return sorted(
        name
        for p in root.iterdir()
        if p.is_dir() and p.name.startswith("list=")
        for name in [p.name.split("=", 1)[1]]
        if name
    )

def _resolve_lists(config: Config, list_name: str | None) -> list[str]:
    name = list_name or config.paths.list_name
    if name.lower() not in _ALL_ALIASES:
        return [name]

    try:
        originals = config.paths.available_lists()
    except FileNotFoundError:
        originals = []
    names = sorted(set(originals) | set(_available_enriched_lists(config)))
    if not names: 
        raise FileNotFoundError(
            "No lists found in the original dataset "
            f"('{config.paths.dataset_root}') or enriched dataset ('{config.paths.enriched_root}')."
        )
    return names

def _load_original(config: Config, lists: list[str]) -> pl.DataFrame | None:
    frames = []
    for name in lists:
        # ``parquet_glob`` may contain '*', so it remains a string until the
        # reader resolves glob patterns.
        glob_path = config.paths.parquet_glob(name)
        try:
            df = read_parquet_safe(glob_path)
        except FileNotFoundError:
            logger.debug("No original Parquet data for list '%s' (%s)", name, glob_path)
            continue
        frames.append(df.with_columns(pl.lit(name).alias(LIST_COLUMN)))
    if not frames:
        return None
    return pl.concat(frames, how="vertical_relaxed")

def _load_enriched(config: Config, lists: list[str]) -> pl.DataFrame | None:
    frames = []
    for name in lists:
        path = Path(config.paths.enriched_parquet_path(name))
        if not path.exists():
            logger.debug("No enriched Parquet data for list '%s' (%s)", name, path)
            continue
        df = pl.read_parquet(path).with_columns(pl.lit(name).alias(LIST_COLUMN))
        frames.append(df)
    if not frames:
        return None
    return pl.concat(frames, how="vertical_relaxed")

def _tables_referenced(query: str) -> frozenset[str]:
    """Return local tables referenced by an SQL query.

    This delays expensive REPL reads. If the expected SQL subset cannot be
    identified, both tables are loaded to preserve compatibility.
    """
    tables = frozenset(match.group(1).lower() for match in _TABLE_REFERENCE.finditer(query))
    return tables or _KNOWN_TABLES


def build_context(
    config: Config,
    list_name: str | None = None,
    tables: Collection[str] | None = None,
) -> pl.SQLContext:
    lists = _resolve_lists(config, list_name)
    requested_tables = set(tables or _KNOWN_TABLES)
    unknown_tables = requested_tables - _KNOWN_TABLES
    if unknown_tables:
        raise ValueError(f"Unknown table(s): {', '.join(sorted(unknown_tables))}")

    original = _load_original(config, lists) if ORIGINAL_TABLE in requested_tables else None
    enriched = _load_enriched(config, lists) if ENRICHED_TABLE in requested_tables else None

    frames: dict[str, pl.LazyFrame] = {}
    if ORIGINAL_TABLE in requested_tables and original is not None:
        frames[ORIGINAL_TABLE] = original.lazy()
    elif ORIGINAL_TABLE in requested_tables:
        logger.warning(
            "No original Parquet data found for lists: %s. Check paths.dataset_root in config.toml.",
            lists,
        )
    if ENRICHED_TABLE in requested_tables and enriched is not None:
        frames[ENRICHED_TABLE] = enriched.lazy()
    elif ENRICHED_TABLE in requested_tables:
        logger.warning(
            "No enriched Parquet data found for lists: %s. Check paths.enriched_root in config.toml.",
            lists,
        )
    if not frames:
        raise FileNotFoundError(
            "No Parquet data found for requested tables "
            f"({', '.join(sorted(requested_tables))}) and lists {lists}. "
            "Check paths.dataset_root and paths.enriched_root in config.toml."
        )
    return pl.SQLContext(frames, eager=True)

def run_query(config: Config, query: str, list_name: str | None = None) -> pl.DataFrame: 
    ctx = build_context(config, list_name, _tables_referenced(query))
    logger.info("Available tables: %s", ", ".join(sorted(ctx.tables())))
    return ctx.execute(query)

def _infer_format(output: str, fmt: str | None) -> str:
    if fmt:
        if fmt not in _EXPORTERS:
            raise ValueError(
                f"Unknown format: {fmt!r}. Use one of: {', '.join(_EXPORTERS)}."
            )
        return fmt
    suffix = Path(output).suffix.lower()
    inferred = _EXTENSION_FORMATS.get (suffix)
    if inferred is None:
        raise ValueError(
            f"Could not infer a format from {output!r}. "
            f"Pass --format ({', '.join(_EXPORTERS)})."
        )
    return inferred

def export_result(df: pl.DataFrame, output: str, fmt: str | None = None) -> None:
    resolved = _infer_format (output, fmt)
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _EXPORTERS[resolved] (df, str(out_path))
    logger.info("Result (%d rows) saved to %s (%s).", df.height, out_path, resolved)

def _print_result(result: pl.DataFrame, limit: int) -> None:
    tbl_rows = result.height if limit <= 0 else limit
    with pl.Config(tbl_rows=tbl_rows):
        print(result)

def _print_catalog(ctx: pl.SQLContext) -> None:
    tables = sorted(ctx.tables())
    print(f"Available tables: {', '.join(tables)}\n")
    for name in tables:
        schema = ctx.execute (f"SELECT FROM {name} LIMIT 0").schema
        cols= ", ".join(f"{col} {dtype}" for col, dtype in schema.items())
        print(f"{name}: {cols}\n")

def _read_multiline() -> str | None:
    first = input("sql> ").strip()
    if not first:
        return None
    if first.rstrip(";").strip().lower() in _EXIT_COMMANDS:
        return first
    lines = [first]
    while not lines[-1].rstrip().endswith(";"):
        cont = input("...> ").rstrip()
        if cont:
            lines.append(cont)
    return "\n".join(lines)

def run_repl(
    config: Config,
    list_name: str | None = None,
    output: str| None = None,
    fmt: str | None = None,
    limit: int = 20,
)-> None:
    contexts: dict[frozenset[str], pl.SQLContext] = {}
    print("Tables are loaded on demand: original, enriched.\n")
    print('Enter an SQL query ending in ";" (exit; / Ctrl+C / Ctrl+D to quit).\n')
    while True:
        try:
            query = _read_multiline()
            if query is None:
                continue
            if query.rstrip(";").strip().lower() in _EXIT_COMMANDS:
                print("Saindo.")
                break

            tables = _tables_referenced(query)
            ctx = contexts.get(tables)
            if ctx is None:
                logger.info("Loading tables: %s", ", ".join(sorted(tables)))
                ctx = build_context(config, list_name, tables)
                contexts[tables] = ctx

            start = time.perf_counter()
            result = ctx.execute(query)
            elapsed = time.perf_counter() - start

            _print_result(result, limit) 
            print(f"! {result.height} row(s) in {elapsed:.4f}s.")
            if output:
                export_result(result, output, fmt)

        except(KeyboardInterrupt, EOFError):
            print("\nExiting.")
            break
        except Exception as exc: 
            print(f"Error: {exc}\n")

def run(
    config: Config,
    query: str | None = None,
    list_name: str | None = None,
    output: str | None = None,
    fmt: str | None = None,
    limit: int = 20
) -> pl.DataFrame | None:

    if query is None: 
        run_repl(config, list_name, output, fmt, limit) 
        return None

    result = run_query(config, query, list_name) 
    logger.info("Query returned %d row(s).", result.height)
    _print_result(result, limit)
    if output: 
        export_result(result, output, fmt)
    return result
