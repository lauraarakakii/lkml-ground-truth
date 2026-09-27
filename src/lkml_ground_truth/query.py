"""SQL queries against the 'original' and 'enriched' Parquet datasets.

Both datasets are laid out as Hive partitions (``list=<name>/...``), the same
convention used by MailingListsHeritage. This module registers each root
directory as a *partitioned* Parquet table with Apache Arrow DataFusion
(``datafusion.SessionContext``) -- the same engine used by
``analysis/src/mlh_analysis/sql_querier.py`` in MLH -- instead of eagerly
reading every ``.parquet`` file with Polars.

Registration only inspects Parquet footers/partition directory names, so it
stays fast (and safe for ``DESCRIBE``) no matter how large the dataset is.
Filtering by list becomes a ``WHERE list IN (...)`` view, which DataFusion
turns into partition pruning: only the matching ``list=<name>`` directories
are ever opened for actual row data. The final result is materialized to
Polars (``.to_polars()``) only once, at the very end of a query, so
``export_result``, ``_print_result`` and friends keep working unchanged.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Collection
from pathlib import Path

import polars as pl
from datafusion import SessionContext

try:
    import readline  # noqa: F401
except ImportError:
    pass

from .config import Config

logger = logging.getLogger(__name__)

ORIGINAL_TABLE = "original"
ENRICHED_TABLE = "enriched"
JOIN_KEY = "message_id"
LIST_COLUMN = "list"

_KNOWN_TABLES = frozenset((ORIGINAL_TABLE, ENRICHED_TABLE))

# Public view name -> hidden table name holding the *unfiltered*,
# hive-partitioned dataset it is derived from.
_RAW_TABLE_NAMES = {
    ORIGINAL_TABLE: "_original_raw",
    ENRICHED_TABLE: "_enriched_raw",
}

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


def _partition_names(root: Path) -> set[str]:
    """Names exposed by ``list=<name>`` subdirectories, read from disk only.

    This never opens a Parquet file: it is just a directory listing, used to
    decide whether a root has any data for the requested lists before
    registering it.
    """
    if not root.is_dir():
        return set()
    names = (
        p.name.split("=", 1)[1]
        for p in root.iterdir()
        if p.is_dir() and p.name.startswith(f"{LIST_COLUMN}=")
    )
    return {name for name in names if name}


def _quote_sql_literal(value: str) -> str:
    return value.replace("'", "''")


def _register_partitioned_root(ctx: SessionContext, raw_name: str, root: Path) -> bool:
    """Register ``root`` as a Hive-partitioned Parquet table (lazy).

    DataFusion only reads Parquet footers and partition directory names for
    this -- never row data -- which is what makes ``DESCRIBE`` and schema
    inspection instant regardless of dataset size. Returns ``False`` when the
    directory does not exist so callers can log and skip it, mirroring the
    previous "no data found" behavior.
    """
    if not root.is_dir():
        return False
    ctx.register_parquet(raw_name, str(root), table_partition_cols=[(LIST_COLUMN, "string")])
    return True


def _create_filtered_view(
    ctx: SessionContext, view_name: str, raw_name: str, lists: list[str]
) -> None:
    """Create/replace ``view_name`` as ``raw_name`` restricted to ``lists``.

    The ``WHERE list IN (...)`` predicate is pushed down by DataFusion as
    partition pruning: only the ``list=<name>`` directories that match are
    ever opened for row data, equivalent to what the old code did by loading
    only the requested lists -- but without materializing anything eagerly.
    """
    values = ", ".join(f"'{_quote_sql_literal(name)}'" for name in lists)
    ctx.sql(
        f"CREATE OR REPLACE VIEW {view_name} AS "
        f"SELECT * FROM {raw_name} WHERE {LIST_COLUMN} IN ({values})"
    )


class QueryContext:
    """A DataFusion ``SessionContext`` exposing ``original``/``enriched`` views.

    Thin wrapper kept for interface compatibility with the rest of this
    module (and any external callers): ``.tables()`` lists the views that
    actually have data, ``.execute()`` runs SQL and materializes the result
    to a Polars ``DataFrame`` only at the end, and ``.schema()`` supports the
    REPL's startup catalog via ``DESCRIBE``.
    """

    def __init__(self, ctx: SessionContext, tables: frozenset[str]) -> None:
        self._ctx = ctx
        self._tables = tables

    def tables(self) -> frozenset[str]:
        return self._tables

    def execute(self, query: str) -> pl.DataFrame:
        return self._ctx.sql(query).to_polars()

    def schema(self, table_name: str) -> pl.DataFrame:
        return self._ctx.sql(f"DESCRIBE {table_name}").to_polars()


def build_context(
    config: Config,
    list_name: str | None = None,
    tables: Collection[str] | None = None,
) -> QueryContext:
    lists = _resolve_lists(config, list_name)
    requested_tables = set(tables or _KNOWN_TABLES)
    unknown_tables = requested_tables - _KNOWN_TABLES
    if unknown_tables:
        raise ValueError(f"Unknown table(s): {', '.join(sorted(unknown_tables))}")

    ctx = SessionContext()
    available_tables: set[str] = set()

    if ORIGINAL_TABLE in requested_tables:
        root = Path(config.paths.dataset_root)
        raw_name = _RAW_TABLE_NAMES[ORIGINAL_TABLE]
        matched = lists and (set(lists) & _partition_names(root))
        if matched and _register_partitioned_root(ctx, raw_name, root):
            _create_filtered_view(ctx, ORIGINAL_TABLE, raw_name, sorted(matched))
            available_tables.add(ORIGINAL_TABLE)
        else:
            logger.warning(
                "No original Parquet data found for lists: %s. "
                "Check paths.dataset_root in config.toml.",
                lists,
            )
    if ENRICHED_TABLE in requested_tables:
        root = Path(config.paths.enriched_root)
        raw_name = _RAW_TABLE_NAMES[ENRICHED_TABLE]
        matched = lists and (set(lists) & _partition_names(root))
        if matched and _register_partitioned_root(ctx, raw_name, root):
            _create_filtered_view(ctx, ENRICHED_TABLE, raw_name, sorted(matched))
            available_tables.add(ENRICHED_TABLE)
        else:
            logger.warning(
                "No enriched Parquet data found for lists: %s. "
                "Check paths.enriched_root in config.toml.",
                lists,
            )

    if not available_tables:
        raise FileNotFoundError(
            "No Parquet data found for requested tables "
            f"({', '.join(sorted(requested_tables))}) and lists {lists}. "
            "Check paths.dataset_root and paths.enriched_root in config.toml."
        )
    return QueryContext(ctx, frozenset(available_tables))


def run_query(config: Config, query: str, list_name: str | None = None) -> pl.DataFrame:
    ctx = build_context(config, list_name)
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
    inferred = _EXTENSION_FORMATS.get(suffix)
    if inferred is None:
        raise ValueError(
            f"Could not infer a format from {output!r}. "
            f"Pass --format ({', '.join(_EXPORTERS)})."
        )
    return inferred


def export_result(df: pl.DataFrame, output: str, fmt: str | None = None) -> None:
    resolved = _infer_format(output, fmt)
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _EXPORTERS[resolved](df, str(out_path))
    logger.info("Result (%d rows) saved to %s (%s).", df.height, out_path, resolved)


def _print_result(result: pl.DataFrame, limit: int) -> None:
    tbl_rows = result.height if limit <= 0 else limit
    with pl.Config(tbl_rows=tbl_rows):
        print(result)


def _print_catalog(ctx: QueryContext) -> None:
    """Print a MLH-``sql_querier.py``-style table/column catalog."""
    tables = sorted(ctx.tables())
    print(f"Available tables: {', '.join(tables)}\n")
    for name in tables:
        schema = ctx.schema(name)
        cols = ", ".join(
            f"{row['column_name']} {row['data_type']}" for row in schema.iter_rows(named=True)
        )
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
    output: str | None = None,
    fmt: str | None = None,
    limit: int = 20,
) -> None:
    # Registration is metadata-only (Parquet footers + partition directory
    # names), so it happens once up front and is instant even for very large
    # datasets. The same context is reused for every query in the session --
    # switching which table a query references no longer triggers a reload.
    try:
        ctx = build_context(config, list_name)
    except FileNotFoundError as exc:
        print(f"Error: {exc}")
        return

    _print_catalog(ctx)
    print('Enter an SQL query ending in ";" (exit; / Ctrl+C / Ctrl+D to quit).\n')
    while True:
        try:
            query = _read_multiline()
            if query is None:
                continue
            if query.rstrip(";").strip().lower() in _EXIT_COMMANDS:
                print("Saindo.")
                break

            start = time.perf_counter()
            result = ctx.execute(query)
            elapsed = time.perf_counter() - start

            _print_result(result, limit)
            print(f"! {result.height} row(s) in {elapsed:.4f}s.")
            if output:
                export_result(result, output, fmt)

        except (KeyboardInterrupt, EOFError):
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
    limit: int = 20,
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
