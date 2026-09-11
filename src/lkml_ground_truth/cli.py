"""Entry point de linha de comando (``lkml-ground-truth`` / ``python -m lkml_ground_truth``)."""

from __future__ import annotations

import argparse
import dataclasses
from email.policy import default
import logging
from ntpath import join

from .config import DEFAULT_CONFIG_PATH, load_config
from .enrich import run as run_enrich
from .pipeline import run
from .query import run_query
from .repo_setup import ensure_repo

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="lkml-ground-truth",
        description=(
            "Casa e-mails de patch de um dataset MailingListsHeritage com "
            "commits do repositório git do Linux, usando o motor de "
            "comparação do PaStA."
        ),
    )
    parser.add_argument(
        "-c",
        "--config",
        default=DEFAULT_CONFIG_PATH,
        help=f"Caminho do arquivo de configuração TOML (padrão: {DEFAULT_CONFIG_PATH}).",
    )

    subparsers = parser.add_subparsers(dest="command")

    subparsers.add_parser(
        "run",
        help="Roda o pipeline completo (padrão se nenhum subcomando for passado)."
    )

    clone_parser = subparsers.add_parser(
        "clone-repo",
        help=(
            "Só clona (ou confirma que já existe) o repositório do kernel "
            "configurado em 'paths.repo_path', sem rodar o pipeline. Útil "
            "para deixar o clone rodando separado, já que pode levar horas."
        ),
    )
    clone_parser.add_argument(
        "--force",
        action="store_true",
        help="Clona mesmo com auto_clone=false em config.toml (ignora o toggle).",
    )
    subparsers.add_parser( 
        "enrich",
        help="Junta o CSV de matches de volta no dataset original " \
        "(left join por message_id) e grava um parquet enriquecido " \
        "em 'paths.enriched_root'. Rode depois de 'run'."
    )

    query_parser = subparsers.add_parser( 
        "query",
        help="Roda consulta(s) SQL (Polars SQL) sobre os parquets 'original' e "
        "'enriched' (join por message_id). Sem SQL, abre um prompt interativo "
        "(REPL) para rodar várias consultas em loop.",
    )

    query_parser.add_argument(
    "sql",
    nargs="?",
    default=None,
    help="Consulta SQL. Tabelas 'original' (dataset LKML5Ws) e 'enriched' (matches). "
    "Ex.: \"SELECT * FROM enriched WHERE is_match=true LIMIT 10\". "
    "Se omitida, abre o modo interativo "
    )
    query_parser.add_argument(
        "-l",
        "--list",
        dest="list_name",
        default=None,
        help="Lista a consultar (padrão: 'paths.list_name). Use 'all' para todas "
        "(adiciona a coluna 'list').",
    )
    query_parser.add_argument(
        "--output",
        default=None,
        help="Arquivo de saida. Sem isso, só imprime no termínal."
    )
    query_parser.add_argument(
        "-f",
        "--format",
        dest="fmt",
        choices=("csv", "parquet", "json", "ndjson"),
        default=None,
        help="Formato de exportação (padrão: deduzido pela extensão de --output).",
    )
    query_parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="Máximo de linhas impressas no terminal (0 = todas). Não afeta a "
        "exportação, que grava tudo. Padrão: 20.",
    )
    return parser


def main(argv: list[str] | None = None) -> None:
    args = build_arg_parser().parse_args(argv)
    config = load_config(args.config)

    command = args.command or "run"

    if command == "clone-repo":
        repo_config = config.repo
        if args.force and not repo_config.auto_clone:
            # Ação explícita e manual do usuário: ignora só o toggle
            # auto_clone, mas ensure_repo() ainda pula o clone se o
            # repositório já existir em repo_path.
            repo_config = dataclasses.replace(repo_config, auto_clone=True)
        ensure_repo(repo_config, config.paths.repo_path)
        return

    if command == "enrich":
        run_enrich(config)
        return

    if command == "query":
        run_query(
            config,
            args.sql,
            list_name=args.list_name,
            output=args.output,
            fmt=args.fmt,
            limit=args.limit,
        )
        return

    run(config)


if __name__ == "__main__":
    main()
