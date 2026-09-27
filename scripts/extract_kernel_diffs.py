#!/usr/bin/env python3
"""Exporta commits do clone oficial do Linux para JSON Lines.

Cada linha de saída contém ``commit_id`` e ``diff``. JSONL é usado porque um
diff pode conter vírgulas, aspas e várias linhas sem tornar o arquivo ambíguo.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path


def git(repo: Path, *args: str, input_text: str | None = None) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        input=input_text,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stderr.strip() or "git retornou erro")
    return result.stdout


def commit_ids(args: argparse.Namespace) -> list[str]:
    command = ["log", "--format=%H", "--no-renames"]
    if args.since:
        command.append(f"--since={args.since}")
    if args.until:
        command.append(f"--until={args.until}")
    command.append(args.ref)
    ids_in_period = git(args.repo, *command).splitlines()

    if not args.commit_list:
        return ids_in_period

    wanted = {
        line.strip().lower()
        for line in args.commit_list.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    }
    return [commit_id for commit_id in ids_in_period if commit_id.lower() in wanted]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True, help="Clone local do Linux.")
    parser.add_argument("--output", type=Path, required=True, help="Arquivo .jsonl de saída.")
    parser.add_argument("--ref", default="HEAD", help="Ref a percorrer (padrão: HEAD).")
    parser.add_argument("--since", help="Data inicial aceita pelo git, por exemplo 2025-01-01.")
    parser.add_argument("--until", help="Data final aceita pelo git, por exemplo 2025-12-31.")
    parser.add_argument(
        "--commit-list",
        type=Path,
        help="Arquivo com um commit hash por linha; limita a exportação a esta lista.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if not args.repo.is_dir():
        raise SystemExit(f"Clone Git não encontrado: {args.repo}")
    if args.commit_list and not args.commit_list.is_file():
        raise SystemExit(f"Lista de commits não encontrada: {args.commit_list}")

    try:
        ids = commit_ids(args)
    except RuntimeError as exc:
        raise SystemExit(f"Não foi possível consultar o repositório: {exc}") from exc

    args.output.parent.mkdir(parents=True, exist_ok=True)
    written = 0
    with args.output.open("w", encoding="utf-8") as output:
        for commit_id in ids:
            try:
                diff = git(
                    args.repo,
                    "show",
                    "--format=",
                    "--patch",
                    "--no-ext-diff",
                    "--no-renames",
                    commit_id,
                )
            except RuntimeError as exc:
                print(f"AVISO: ignorando {commit_id}: {exc}", file=sys.stderr)
                continue
            output.write(json.dumps({"commit_id": commit_id, "diff": diff}, ensure_ascii=False))
            output.write("\n")
            written += 1

    print(f"Exportados {written} commits para {args.output}")


if __name__ == "__main__":
    main()
