# Análises

Esta pasta guarda análises reproduzíveis sobre o resultado do matching. Cada
função em `fixed.py` responde uma pergunta específica com Polars Lazy e gera
um CSV em `output/analysis/` — diretório ignorado pelo Git.

Ela usa o mesmo contexto de consulta do projeto; portanto, lê as tabelas Parquet
`original` e `enriched` definidas no `config.toml`, sem criar cópias dos
datasets.

## Executar

Depois de rodar o pipeline e `make enrich`:

```bash
# Da raiz do repositório
make analysis ANALYSIS=dataset_coverage LIST=all

# Ou diretamente nesta pasta
make -C src/lkml_ground_truth/analysis run ANALYSIS=commit_reuse LIST=netdev
```

## Consulta SQL interativa

`sql_querier.py` é a entrada de consultas desta pasta, equivalente ao
componente de análise do MLH-Archiver. Sem SQL, abre um REPL; com SQL, executa
uma única consulta:

```bash
make -C src/lkml_ground_truth/analysis query LIST=all
make -C src/lkml_ground_truth/analysis query LIST=netdev SQL='SELECT * FROM enriched LIMIT 10'
```

Ele é uma interface para o mesmo contexto de consulta do projeto, então as
tabelas disponíveis são `original` e `enriched`.

Use `make -C src/lkml_ground_truth/analysis help` para a lista de análises. Para escolher outro
arquivo de configuração ou destino dos CSVs:

```bash
make -C src/lkml_ground_truth/analysis run ANALYSIS=score_bands \
  CONFIG=/caminho/config.toml RESULTS_DIR=/tmp/lkml-analysis
```

## Análises fixas disponíveis

| Análise | O que revela |
| --- | --- |
| `dataset_coverage` | Cobertura do pipeline em relação a todos os e-mails: fonte original, patches avaliados, matches, matches confiáveis e erros. Usa `original` e `enriched`. |
| `match_coverage` | Cobertura, matches confiáveis, candidatos ausentes, erros e score médio por lista. |
| `score_bands` | Quantos patches estão em cada decisão do pipeline: confiável, para revisão, sem candidato ou abaixo do limiar. |
| `match_errors` | Erros de busca de candidatos agrupados, para diagnosticar problemas sistemáticos. |
| `commit_reuse` | Commits associados a vários e-mails; são candidatos a séries, reenvios ou falsos positivos que merecem revisão. |
| `matched_pairs` | Pares e-mail/commit com as duas datas, úteis para analisar a latência até a integração e validar casos individuais. |

`commit_date` é a data do *committer* no Git, em ISO 8601. Para análises
temporais, ela só estará presente em execuções do pipeline feitas após a
adição dessa coluna.

## Adicionar uma descoberta

1. Crie uma função em `fixed.py`, usando `scan_original()` e/ou `scan_enriched()`.
2. Documente a pergunta e como interpretar o resultado nesta tabela.
3. Adicione a função em `ANALYSES`, execute `make analysis ANALYSIS=<nome>` e mantenha o código no Git;
   o CSV resultante fica em `output/analysis/`.
