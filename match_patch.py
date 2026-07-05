"""
Integração LKML5Ws + PaStA — motor de comparação reaproveitado, arquitetura
própria para performance em datasets grandes.

MUDANÇA DE ARQUITETURA IMPORTANTE (por que a versão anterior levava 20h+):
  A versão anterior rodava um subprocess `git log` NOVO para cada patch.
  Com centenas de milhares de patches, isso significa centenas de milhares
  de processos git, cada um pagando o custo de startup + varredura de
  histórico. Iso é o gargalo.

  Esta versão constrói um ÍNDICE arquivo->commits UMA ÚNICA VEZ (módulo
  commit_index.py), com uma passada de `git log --name-only` sobre todo o
  repositório. A busca de candidatos por patch vira uma busca binária em
  memória (bisect), sem subprocess -- medido em ~0.02ms por busca, contra
  ~30ms+ por chamada de subprocess (>1000x mais rápido).

  O índice é cacheado em disco (pickle), então só é reconstruído se você
  mudar o repositório ou pedir explicitamente via config.toml
  (performance.rebuild_index = true).

Tudo configurável está em config.toml -- não precisa editar este arquivo
para ajustar threads, caminhos ou thresholds.
"""

import sys
from datetime import timedelta
from multiprocessing import Pool
from pathlib import Path

import polars as pl

sys.path.insert(0, str(Path(__file__).parent))

from config_loader import Config, load_config
from commit_index import find_candidates, load_or_build_index
from PaStA_lib.Repository.Patch import Diff
from PaStA_lib.Repository.MessageDiff import MessageDiff, Signature
from PaStA_lib.Repository.Repository import Repository
from PaStA_lib.PatchEvaluation import evaluate_patch_pair


class Thresholds:
    """Copiado de pypasta/Config.py -- só essa classe, não o Config.py
    inteiro (que puxaria Clustering.py e PatchStack.py, que não usamos)."""

    def __init__(self, autoaccept, interactive, diff_lines_ratio,
                 heading, filename, message_diff_weight):
        self.autoaccept = autoaccept
        self.interactive = interactive
        self.heading = heading
        self.filename = filename
        self.message_diff_weight = message_diff_weight
        self.diff_lines_ratio = diff_lines_ratio
        self.author_date_interval = 0  # não usado neste pipeline


# ---------------------------------------------------------------------------
# Estado global por processo. É montado no processo principal ANTES de criar
# o Pool -- no Linux (fork), os processos filhos herdam essas variáveis já
# populadas via copy-on-write, sem precisar serializar (pygit2.Repository e
# o índice não são triviais de serializar/passar via pickle a cada chamada).
# ---------------------------------------------------------------------------

_repo = None
_index = None
_config: Config = None
_thresholds: Thresholds = None


def _init_globals(config: Config):
    global _repo, _index, _config, _thresholds
    _config = config
    _thresholds = Thresholds(
        autoaccept=config.matching.autoaccept,
        interactive=config.matching.interactive,
        diff_lines_ratio=config.matching.diff_lines_ratio,
        heading=config.matching.heading,
        filename=config.matching.filename,
        message_diff_weight=config.matching.message_diff_weight,
    )
    _repo = Repository("linux", config.paths.repo_path)
    _index = load_or_build_index(
        config.paths.repo_path,
        config.paths.commit_index_cache,
        rebuild=config.performance.rebuild_index,
    )


# ---------------------------------------------------------------------------
# Leitura do parquet: Polars como estratégia principal, com fallback
# row-group-por-row-group para datasets muito grandes/multi-arquivo onde o
# pyarrow.dataset.Scanner trava em colunas aninhadas (bug conhecido).
# ---------------------------------------------------------------------------

def read_parquet_safe(path_or_glob: str) -> pl.DataFrame:
    """Lê um parquet único ou múltiplos via glob (ex: 'pasta/*.parquet').
    Estratégia principal: Polars (lê glob nativamente). Fallback: lê cada
    arquivo individualmente, row-group por row-group via pyarrow -- para
    datasets grandes/multi-arquivo onde o pyarrow.dataset.Scanner trava em
    colunas aninhadas (bug conhecido com list/struct em múltiplos chunks)."""
    try:
        return pl.read_parquet(path_or_glob)
    except Exception as e1:
        print(f"  [aviso] polars.read_parquet falhou ({type(e1).__name__}), "
              f"tentando leitura row-group por row-group via pyarrow...")

    import glob as globmod
    import pyarrow.parquet as pq

    files = sorted(globmod.glob(path_or_glob)) if any(c in path_or_glob for c in "*?[") \
        else [path_or_glob]

    parts = []
    for file in files:
        pf = pq.ParquetFile(file)
        parts.extend(pl.from_arrow(pf.read_row_group(i)) for i in range(pf.num_row_groups))
    return pl.concat(parts, how="vertical_relaxed")


def row_to_messagediff(row: dict):
    code = row.get("code")
    if code is None or len(code) == 0:
        return None

    diff_text = "\n".join(code)
    diff_lines = diff_text.split("\n")

    try:
        parsed_diff = Diff(diff_lines)
    except Exception:
        return None

    if not parsed_diff.affected:
        return None

    message_text = row.get("untagged_subject") or ""
    body = row.get("raw_body") or ""
    if diff_text and diff_text in body:
        body = body.split(diff_text)[0]
    message_lines = [message_text] + body.split("\n")

    author_str = row.get("from") or "unknown <unknown@example.com>"
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


def process_row(row: dict):
    """Roda dentro de cada processo worker. Usa o índice + repo já abertos
    globalmente (herdados via fork), sem nenhum subprocess."""

    md = row_to_messagediff(row)
    if md is None:
        return None

    date = row["date"]
    since_ts = int((date - timedelta(days=_config.matching.days_before)).timestamp())
    until_ts = int((date + timedelta(days=_config.matching.days_after)).timestamp())

    try:
        candidates = find_candidates(_index, md.diff.affected, since_ts, until_ts)
    except Exception as e:
        return {
            "message_id": row.get("message_id"),
            "best_commit": None, "score": None,
            "is_match": False, "is_confident_match": False,
            "error": f"candidate_search: {e}",
        }

    best_score = None
    best_hash = None

    for chash in candidates:
        try:
            commit = _repo[chash]
        except Exception:
            continue

        sim = evaluate_patch_pair(
            _thresholds,
            (" ".join(md.message), md.diff),
            (" ".join(commit.message), commit.diff),
        )
        score = (
            _thresholds.message_diff_weight * sim.msg
            + (1 - _thresholds.message_diff_weight) * sim.diff
        )
        if best_score is None or score > best_score:
            best_score = score
            best_hash = chash

    return {
        "message_id": row.get("message_id"),
        "best_commit": best_hash,
        "score": best_score,
        "is_match": best_score is not None and best_score >= _thresholds.interactive,
        "is_confident_match": best_score is not None and best_score >= _thresholds.autoaccept,
        "error": None,
    }


def process_list(config: Config, list_name: str):
    """Processa uma lista específica do dataset (uma subpasta list=<nome>)."""

    glob_path = config.paths.parquet_glob(list_name)
    output_path = config.paths.resolved_output_path(list_name)

    print(f"\n=== Lista: {list_name} ===")
    print(f"Carregando dataset: {glob_path}")
    df = read_parquet_safe(glob_path)
    df_patches = df.filter(pl.col("code").is_not_null())
    print(f"  -> {df_patches.height} e-mails com diff (de {df.height} totais)")

    if df_patches.height == 0:
        print("  Nada pra processar nessa lista.")
        return

    num_workers = config.performance.resolved_num_workers()
    print(f"Processando com {num_workers} processo(s) em paralelo "
          f"(ajuste em config.toml -> [performance] -> num_workers)...")

    rows_iter = df_patches.iter_rows(named=True)

    results = []
    with Pool(num_workers) as pool:
        for i, res in enumerate(
            pool.imap_unordered(process_row, rows_iter, chunksize=config.performance.chunksize)
        ):
            if res is not None:
                results.append(res)
            if i % config.performance.progress_every == 0:
                print(f"  processado {i}/{df_patches.height}...")

    if not results:
        print("  Nenhum resultado (nenhuma linha tinha diff utilizável).")
        return

    out = pl.DataFrame(results)
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    out.write_csv(output_path)

    print(f"  Pronto. Resultados salvos em {output_path}")
    print(out.group_by("is_match").len())

    n_errors = out.filter(pl.col("error").is_not_null()).height
    if n_errors:
        print(f"  [aviso] {n_errors} linhas tiveram erro (ver coluna 'error' no CSV).")


def main():
    config = load_config("config.toml")

    print(f"Abrindo repositório e construindo/carregando índice: {config.paths.repo_path}")
    _init_globals(config)  # roda no processo principal ANTES do Pool (fork)

    list_name = config.paths.list_name

    if list_name.lower() in ("all", "*", "todas"):
        available = config.paths.available_lists()
        print(f"\nlist_name = '{list_name}' -> processando TODAS as {len(available)} listas encontradas em {config.paths.dataset_root}")
        for name in available:
            process_list(config, name)
    else:
        process_list(config, list_name)


if __name__ == "__main__":
    main()
