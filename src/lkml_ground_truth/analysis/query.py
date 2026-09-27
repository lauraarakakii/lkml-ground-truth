"""SQL queries against the 'original' and 'enriched' Parquet datasets.

Both datasets are laid out as Hive partitions (``list=<name>/...``), the same
convention used by MailingListsHeritage. This module runs queries with
Apache Arrow DataFusion (``datafusion.SessionContext``) -- the same engine
used by ``analysis/src/mlh_analysis/sql_querier.py`` in MLH -- instead of
eagerly reading every ``.parquet`` file with Polars.

Only the ``list=<name>`` directories for the *requested* lists are ever
registered, and registration only inspects Parquet footers, so it stays fast
(and safe for ``DESCRIBE``) no matter how large the dataset is. Earlier this
module registered the whole ``dataset_root``/``enriched_root`` as one
Hive-partitioned table and filtered with ``WHERE list IN (...)``: that forced
DataFusion to merge the schema of *every* list up front, so a single
mismatched column anywhere in the dataset (e.g. an ``enriched`` run that
wrote ``score`` as a string for one list) broke every query, even ones for an
unrelated, perfectly fine list. Registering per-list avoids that -- a
one-list query never looks at another list's files at all -- and when
multiple lists *are* requested together (``--list all`` or a query joining
several), any mismatched columns across them are reconciled the same way the
previous Polars implementation's ``pl.concat(..., how="vertical_relaxed")``
did: matching types are kept as-is, numeric types are widened, and anything
else (e.g. a numeric/string clash) is coerced to a string.

The final result is materialized to Polars (``.to_polars()``) only once, at
the very end of a query, so ``export_result``, ``_print_result`` and friends
keep working unchanged.
"""

from __future__ import annotations

import functools
import logging
import time
from collections.abc import Collection
from pathlib import Path

import polars as pl
import pyarrow as pa
from datafusion import DataFrame as DFDataFrame
from datafusion import SessionContext, column, lit

try:
    import readline  # noqa: F401
except ImportError:
    pass

from ..config import Config

logger = logging.getLogger(__name__)

ORIGINAL_TABLE = "original"
ENRICHED_TABLE = "enriched"
JOIN_KEY = "message_id"
LIST_COLUMN = "list"

_KNOWN_TABLES = frozenset((ORIGINAL_TABLE, ENRICHED_TABLE))

# Public view name -> prefix used for the private, per-list raw tables it is
# built from (e.g. "_original_raw_0", "_original_raw_1", ...).
_RAW_TABLE_PREFIXES = {
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
    decide which of the requested lists actually have data before
    registering anything.
    """
    if not root.is_dir():
        return set()
    names = (
        p.name.split("=", 1)[1]
        for p in root.iterdir()
        if p.is_dir() and p.name.startswith(f"{LIST_COLUMN}=")
    )
    return {name for name in names if name}


def _has_parquet_files(directory: Path) -> bool:
    return any(directory.glob("*.parquet"))


def _is_string_like(data_type: pa.DataType) -> bool:
    return (
        pa.types.is_string(data_type)
        or pa.types.is_large_string(data_type)
        or pa.types.is_string_view(data_type)
    )


def _unify_type(types: list[pa.DataType]) -> pa.DataType:
    """Pick a common Arrow type for the same column seen across lists.

    Mirrors the leniency of Polars' ``pl.concat(..., how="vertical_relaxed")``,
    which the previous implementation relied on: identical types are kept,
    null-typed (all-missing) columns defer to whatever concrete type shows up
    elsewhere, mixed integer/float columns widen to float64, and anything
    else that cannot be reconciled (e.g. a numeric column next to a string
    one) falls back to a string, which every scalar type can be cast to.
    """
    concrete = [t for t in types if not pa.types.is_null(t)]
    if not concrete:
        return pa.null()
    first = concrete[0]
    if all(t.equals(first) for t in concrete):
        return first
    if any(_is_string_like(t) for t in concrete):
        return pa.string()
    if all(pa.types.is_integer(t) or pa.types.is_floating(t) for t in concrete):
        return pa.float64() if any(pa.types.is_floating(t) for t in concrete) else pa.int64()
    return pa.string()


def _register_list_tables(
    ctx: SessionContext, raw_prefix: str, root: Path, lists: list[str]
) -> list[tuple[str, str, pa.Schema]]:
    """Register one raw table per ``list=<name>`` directory that has data.

    Only the requested ``lists`` are touched -- never the rest of ``root`` --
    so a query for one list can never be broken by another list's data, and
    registration stays metadata-only (Parquet footers, no row data).
    Returns ``(raw_table_name, list_name, schema)`` for each list found.
    """
    entries: list[tuple[str, str, pa.Schema]] = []
    for name in lists:
        partition_dir = root / f"{LIST_COLUMN}={name}"
        if not partition_dir.is_dir() or not _has_parquet_files(partition_dir):
            continue
        raw_name = f"{raw_prefix}_{len(entries)}"
        ctx.register_parquet(raw_name, str(partition_dir))
        entries.append((raw_name, name, ctx.table(raw_name).schema()))
    return entries


def _build_union_view(
    ctx: SessionContext, view_name: str, entries: list[tuple[str, str, pa.Schema]]
) -> None:
    """Create ``view_name`` as the union of each list's raw table.

    Column order follows first appearance across ``entries``; each list's
    columns are cast to the unified type computed by ``_unify_type``, and a
    typed ``NULL`` fills in columns a given list doesn't have. A literal
    ``list`` column is added, exactly as the old ``pl.lit(name)`` did.
    """
    column_order: list[str] = []
    seen: set[str] = set()
    for _, _, schema in entries:
        for field in schema:
            if field.name not in seen:
                seen.add(field.name)
                column_order.append(field.name)

    target_types = {
        col: _unify_type(
            [schema.field(col).type for _, _, schema in entries if col in schema.names]
        )
        for col in column_order
    }

    frames: list[DFDataFrame] = []
    for raw_name, name, schema in entries:
        exprs = []
        for col in column_order:
            target = target_types[col]
            expr = column(col).cast(target) if col in schema.names else lit(None).cast(target)
            exprs.append(expr.alias(col))
        exprs.append(lit(name).alias(LIST_COLUMN))
        frames.append(ctx.table(raw_name).select(*exprs))

    unioned = functools.reduce(lambda a, b: a.union(b), frames)
    ctx.register_view(view_name, unioned)


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
        entries = _register_list_tables(ctx, _RAW_TABLE_PREFIXES[ORIGINAL_TABLE], root, lists)
        if entries:
            _build_union_view(ctx, ORIGINAL_TABLE, entries)
            available_tables.add(ORIGINAL_TABLE)
        else:
            logger.warning(
                "No original Parquet data found for lists: %s. "
                "Check paths.dataset_root in config.toml.",
                lists,
            )
    if ENRICHED_TABLE in requested_tables:
        root = Path(config.paths.enriched_root)
        entries = _register_list_tables(ctx, _RAW_TABLE_PREFIXES[ENRICHED_TABLE], root, lists)
        if entries:
            _build_union_view(ctx, ENRICHED_TABLE, entries)
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
