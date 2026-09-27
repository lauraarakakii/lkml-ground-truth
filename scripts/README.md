# Projeto adicional: integração e validação

Os três scripts deste diretório são independentes do pipeline principal. Eles
recebem os seus artefatos já prontos e não alteram a base LKML5Ws.

## 1. Exportar a lista A do clone oficial do Linux

O formato recomendado é JSON Lines (`.jsonl`): uma linha por commit, com
`commit_id` e `diff`. Ele preserva diffs multilinha sem os problemas de CSV.

```bash
python src/scripts/extract_kernel_diffs.py \
  --repo /caminho/para/linux \
  --ref master \
  --since 2026-01-01 --until 2026-06-30 \
  --output output/list_a_kernel.jsonl
```

Para filtrar uma lista específica de commits, crie `commits.txt` com um hash
por linha e acrescente `--commit-list commits.txt`. O script usa este comando
Git para determinar os commits no período (e em seguida usa `git show` para
obter o diff de cada commit):

```bash
git -C /caminho/para/linux log --format=%H --no-renames \
  --since=2026-01-01 --until=2026-06-30 master
```

O clone pode ser obtido com:

```bash
git clone https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git /caminho/para/linux
```

## 2. Integrar A, B e C

A lista B deve ser um CSV com cabeçalho `message_id,diff`; o módulo `csv` lê
corretamente um diff com vírgulas ou quebras de linha desde que ele esteja
entre aspas, como determina CSV. A lista C pode ser o CSV gerado pelo projeto
principal ou Parquet; o campo `best_commit` é aceito como alias de
`commit_hash`.

Por padrão só são integradas linhas de C com `is_match=true`:

```bash
python src/scripts/integrate_lists.py \
  --git-list output/list_a_kernel.jsonl \
  --lkml-list /caminho/para/list_b.csv \
  --correlation output/matches.csv \
  --output output/integrated.jsonl
```

Use `--include-non-matches` para não aplicar esse filtro. A saída contém
`message_id`, `commit_hash`, `github_diff` e `lkml_diff`.

## 3. Validar no navegador (desktop ou celular)

```bash
python src/scripts/review_server.py \
  --integrated output/integrated.jsonl \
  --responses output/review_responses.csv \
  --reviewer laura
```

Abra `http://localhost:8000` no computador. Para abrir no celular, conecte-o
à mesma rede e use `http://IP-DO-COMPUTADOR:8000`; o servidor já escuta em
`0.0.0.0`. Cada clique é salvo imediatamente em CSV append-only e sincronizado
no disco. Ao reiniciar com o mesmo `--reviewer`, os `message_id` já avaliados
são pulados. Não exponha essa porta diretamente na internet.
