"""
Integração LKML5Ws + PaStA (reaproveitando só o motor de comparação)
=====================================================================

O que este script faz:
  1. Carrega seu parquet (formato LKML5Ws) com a coluna 'code' (diff cru).
  2. Constrói um objeto MessageDiff (classe do PaStA) para cada e-mail com patch.
  3. Abre o repositório git (resources/linux/repo) via a classe Repository do PaStA.
  4. Para cada patch, busca candidatos a commit: usa `git log` (subprocess) filtrando
     por arquivo tocado + janela de tempo, o que é MUITO mais rápido que comparar
     contra todo o histórico do kernel.
  5. Roda evaluate_patch_pair (motor de fuzzy match do PaStA) entre o patch do
     e-mail e cada candidato.
  6. Salva o melhor match (se acima do threshold) num CSV/parquet de saída.

O QUE NÃO É REAPROVEITADO DO PASTA (de propósito):
  - Mbox.py / PubInbox (clonagem de e-mail via git) -> seus dados já vêm prontos
  - Config.py / patch-stack definitions -> não precisamos do modo patch-stack
  - Clustering.py -> não precisamos de classes de equivalência multi-versão aqui
"""

import subprocess
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).parent))

from pasta_lib.Repository.Patch import Diff
from pasta_lib.Repository.MessageDiff import MessageDiff, Signature
from pasta_lib.Repository.Repository import Repository, Commit
from pasta_lib.PatchEvaluation import evaluate_patch_pair


# Thresholds copiado de pypasta/Config.py — copiamos só essa classe (não o
# Config.py inteiro) porque o Config.py original importa Clustering.py e
# PatchStack.py, que não usamos aqui.
class Thresholds:
    def __init__(self, autoaccept, interactive, diff_lines_ratio,
                 heading, filename, message_diff_weight,
                 author_date_interval):
        self.autoaccept = autoaccept
        self.interactive = interactive
        self.heading = heading
        self.filename = filename
        self.message_diff_weight = message_diff_weight
        self.diff_lines_ratio = diff_lines_ratio
        self.author_date_interval = author_date_interval

# ---------------------------------------------------------------------------
# CONFIGURAÇÃO — ajuste esses caminhos/parâmetros pro seu ambiente
# ---------------------------------------------------------------------------

REPO_PATH = "resources/linux/repo"        # caminho do repo git já clonado
PARQUET_PATH = "list_data.parquet"        # seu arquivo LKML5Ws
OUTPUT_PATH = "matches_output.csv"

# Janela de tempo: quantos dias depois do envio do e-mail ainda vale procurar
# um commit correspondente. Patches do kernel geralmente são aceitos em
# semanas/meses; alguns demoram bem mais. Ajuste conforme seu caso.
DAYS_AFTER = 365
DAYS_BEFORE = 3  # margem de segurança (fuso horário, patch aplicado antes do envio p/ lista)

# Thresholds do PaStA (valores de exemplo usados no projeto original;
# quanto maior, mais rigoroso o match)
THRESHOLDS = Thresholds(
    autoaccept=0.8,          # score >= isso: aceita automaticamente
    interactive=0.5,         # score entre interactive e autoaccept: candidato "duvidoso"
    diff_lines_ratio=0.4,    # descarta pares com tamanho de diff muito diferente
    heading=0.7,
    filename=0.7,
    message_diff_weight=0.5, # 0 = so diff importa, 1 = so mensagem importa
    author_date_interval=0,  # não usado aqui, mantido por compatibilidade
)


# ---------------------------------------------------------------------------
# PASSO 1: construir um MessageDiff a partir de uma linha do seu dataframe
# ---------------------------------------------------------------------------

def row_to_messagediff(row) -> MessageDiff | None:
    """Constrói um objeto MessageDiff (classe do PaStA) a partir de uma linha
    do parquet LKML5Ws. Retorna None se não houver diff utilizável."""

    code = row["code"]
    if code is None or len(code) == 0:
        return None

    # a coluna code vem como array numpy; junta e quebra em linhas de verdade
    diff_text = "\n".join(code)
    diff_lines = diff_text.split("\n")

    try:
        parsed_diff = Diff(diff_lines)
    except Exception:
        # diffs malformados / formatos não suportados (ex: diffs --cc de merge)
        return None

    if not parsed_diff.affected:
        return None

    # mensagem: usamos o subject sem as tags [PATCH v2 ...] como "assunto",
    # e o raw_body como corpo (o que sobra depois de remover o diff cru serve
    # como aproximação da mensagem de commit). Ajuste aqui se seu dataset tiver
    # uma coluna melhor separando mensagem de diff.
    message_text = row.get("untagged_subject") or ""
    body = row.get("raw_body") or ""
    # corta o corpo no ponto onde o diff começa, se possível
    if diff_text and diff_text in body:
        body = body.split(diff_text)[0]
    message_lines = [message_text] + body.split("\n")

    author_str = row.get("from") or "unknown <unknown@example.com>"
    # parsing simples de "Nome <email>"
    if "<" in author_str and ">" in author_str:
        name = author_str.split("<")[0].strip().strip('"')
        email = author_str.split("<")[1].split(">")[0].strip()
    else:
        name, email = author_str, "unknown@example.com"

    date = row.get("date")
    author = Signature(name, email, date)

    content = (message_lines, None, diff_lines)

    md = MessageDiff.__new__(MessageDiff)
    MessageDiff.__init__(md, row["message_id"], content, author)
    return md


# ---------------------------------------------------------------------------
# PASSO 2: gerar candidatos via `git log` (rápido, filtra por arquivo + data)
# ---------------------------------------------------------------------------

def find_candidate_commits(repo_path, affected_files, date, days_before, days_after):
    """Usa `git log` pra achar candidatos rapidamente, sem varrer o repo
    inteiro. Filtra por arquivos tocados + janela de tempo."""

    since = (date - pd.Timedelta(days=days_before)).strftime("%Y-%m-%d")
    until = (date + pd.Timedelta(days=days_after)).strftime("%Y-%m-%d")

    cmd = [
        "git", "-C", repo_path, "log",
        "--since", since, "--until", until,
        "--format=%H",
        "--",
    ] + list(affected_files)

    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        return []
    return [h for h in result.stdout.strip().split("\n") if h]


# ---------------------------------------------------------------------------
# PASSO 3: loop principal
# ---------------------------------------------------------------------------

def main():
    print(f"Abrindo repositório: {REPO_PATH}")
    repo = Repository("linux", REPO_PATH)

    print(f"Carregando dataset: {PARQUET_PATH}")
    df = pd.read_parquet(PARQUET_PATH)
    df_patches = df[df["code"].notna()].copy()
    print(f"  -> {len(df_patches)} e-mails com diff (de {len(df)} totais)")

    results = []

    for idx, row in df_patches.iterrows():
        md = row_to_messagediff(row)
        if md is None:
            continue

        candidates = find_candidate_commits(
            REPO_PATH, md.diff.affected, row["date"], DAYS_BEFORE, DAYS_AFTER
        )

        best_score = None
        best_hash = None

        for chash in candidates:
            try:
                commit = repo[chash]  # usa Repository.get_commit / cache interno
            except KeyError:
                continue

            sim = evaluate_patch_pair(
                THRESHOLDS,
                (" ".join(md.message), md.diff),
                (" ".join(commit.message), commit.diff),
            )

            # combina msg + diff rating pelo peso configurado, igual ao PaStA
            score = (
                THRESHOLDS.message_diff_weight * sim.msg
                + (1 - THRESHOLDS.message_diff_weight) * sim.diff
            )

            if best_score is None or score > best_score:
                best_score = score
                best_hash = chash

        results.append({
            "message_id": row["message_id"],
            "best_commit": best_hash,
            "score": best_score,
            "is_match": (best_score is not None and best_score >= THRESHOLDS.interactive),
            "is_confident_match": (best_score is not None and best_score >= THRESHOLDS.autoaccept),
        })

        if idx % 50 == 0:
            print(f"  processado {idx}/{len(df_patches)}...")

    out = pd.DataFrame(results)
    out.to_csv(OUTPUT_PATH, index=False)
    print(f"\nPronto. Resultados salvos em {OUTPUT_PATH}")
    print(out["is_match"].value_counts())


if __name__ == "__main__":
    main()
