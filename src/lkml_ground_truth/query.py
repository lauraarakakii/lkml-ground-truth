from __future__ import annotations

import logging
import time
import pathlib as Path

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

_ALL_ALIASES = ("all", "*", "todas")
_EXIT_COMMANDS = ("exit", "quit", "sair", r"\q")

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
    """Nomes de lista disponíveis no dataset enriquecido (subpastas ``list=<nome>``)."""
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
            "Nenhuma lista encontrada no dataset original "
            f"('{config.paths.dataset_root}') nem no enriquecido ('{config.paths.enriched_root}')."
        )
    return names

def _load_original(config: Config, lists: list[str]) -> pl.DataFrame | None:
    frames = []
    for name in lists:
        glob_path = Path(config.paths.parquet_glob(name))
        try:
            df = read_parquet_safe(glob_path)
        except FileNotFoundError:
            logger.debug("Sem parquet original para a lista '%s' (%s)", name, glob_path)
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
            logger.debug("Sem parquet enriquecido para a lista '%s' (%s)", name, path)
            continue
        df = pl.read_parquet(path).with_columns(pl.lit(name).alias(LIST_COLUMN))
        frames.append(df)
    if not frames:
        return None
    return pl.concat(frames, how="vertical_relaxed")

def build_context(config: Config, list_name: str | None = None) -> pl.SQLContext:
    lists = _resolve_lists(config, list_name)

    original = _load_original(config, lists)
    enriched = _load_enriched(config, lists)

    frames: dict[str, pl.LazyFrame] = {}
    if original is not None:
        frames[ORIGINAL_TABLE] = original.lazy()
    else:
        logger.warning(
            "Nenhum parquet original encontrado para as listas: %s. "
            "Verifique 'paths.dataset_root' no config.toml",
            lists,
        )
    if enriched is not None:
        frames[ENRICHED_TABLE] = enriched.lazy()
    else:
        logger.warning(
            "Nenhum parquet enriquecido encontrado para as listas: %s. "
            "Verifique 'paths.enriched_root' no config.toml",
            lists,
        )
    if not frames:
        raise FileNotFoundError(
            "Nenhum parquet original nem enriquecido encontrado para as listas: "
            f"{lists}. Verifique 'paths.dataset_root' e 'paths.enriched_root' no config.toml"
        )
    return pl.SQLContext(frames, eager=True)

def run_query(config: Config, query: str, list_name: str | None = None) -> pl.DataFrame: 
    
    ctx = build_context(config, list_name) 
    logger.info("Tabelas disponiveis: %s", ", ".join(sorted(ctx.tables())))
    return ctx.execute(query)

def _infer_format(output: str, fmt: str | None) -> str:
    if fmt:
        if fmt not in _EXPORTERS:
            raise ValueError(
                f"Formato desconhecido: {fmt!r}. Use um de: {', '.join( _EXPORTERS)}."
            )
        return fmt
    suffix = Path(output).suffix.lower()
    inferred = _EXTENSION_FORMATS.get (suffix)
    if inferred is None:
        raise ValueError(
            f"Não deduzi o formato pela extensão de {output!r}. "
            f"Passe --format ({', '.join(_EXPORTERS)})"
        )
    return inferred

def export_result(df: pl.DataFrame, output: str, fmt: str | None = None) -> None:
    resolved = _infer_format (output, fmt)
    out_path = Path(output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    _EXPORTERS[resolved] (df, str(out_path))
    logger.info("Resultado (%d linhas) salvo em %s (%s).", df.height, out_path, resolved)

def _print_result(result: pl.DataFrame, limit: int) -> None:
    tbl_rows = result.height if limit <= 0 else limit
    with pl.Config(tbl_rows=tbl_rows):
        print(result)

def _print_catalog(ctx: pl.SQLContext) -> None:
    tables = sorted(ctx.tables())
    print(f"Tabelas disponiveis: {', '.join(tables)}\n")
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
    ctx = build_context(config, list_name)
    _print_catalog(ctx) 
    print('Digite a consulta SQL terminada por ";" (exit; / Ctrl+C / CtrI+D para sair).\n')
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
            print(f"! {result.height} linha(s) em {elapsed:.4f}s.")
            if output:
                export_result(result, output, fmt)

        except(KeyboardInterrupt, EOFError):
            print("\nSaindo.")
            break
        except Exception as exc: 
            print(f"Erro: {exc}\n")

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
    logger.info("Consulta retornou %d linha(s).", result.height) 
    _print_result(result, limit)
    if output: 
        export_result(result, output, fmt)
    return result