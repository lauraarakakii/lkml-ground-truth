# lkml-ground-truth

Gera um *ground truth* patch → commit para mailing lists do kernel Linux:
casa e-mails de patch (dataset no formato produzido pelo
[MailingListsHeritage](https://github.com/) — parquet particionado por
`list=<nome>/`) com os commits correspondentes no repositório git do
Linux, reaproveitando o motor de comparação do
[PaStA](https://github.com/lfd/PaStA) (Patch Stack Analysis).

## Por que não `git log` por patch

A abordagem ingênua — rodar `git log` uma vez para cada patch — significa
centenas de milhares de subprocessos em datasets grandes, cada um pagando
o custo de startup do git e varrendo o histórico inteiro. Isso é o que
fazia o pipeline levar mais de 20h sem terminar uma única lista.

Em vez disso, o projeto constrói um **índice arquivo → commits** com uma
única passada (`git log --name-only`) sobre todo o histórico do
repositório, cacheado em disco. A busca de candidatos por patch vira uma
busca binária em memória (`bisect`), sem nenhum subprocess — cerca de
1000x mais rápido por busca.

## Estrutura

```
lkml-ground-truth/
├── pyproject.toml          ← dependências, versão, config do ruff/pytest
├── example_config.toml     ← copie para config.toml e ajuste ao seu ambiente
├── Makefile                ← run / test / lint / fmt / clean
├── Containerfile            ← imagem para rodar sem instalar toolchain local
├── noxfile.py               ← sessões `lint` e `tests` (usadas por CI e Makefile)
├── src/lkml_ground_truth/
│   ├── cli.py               ← ponto de entrada (`lkml-ground-truth`)
│   ├── config.py            ← única fonte de configuração (lê config.toml)
│   ├── commit_index.py      ← índice arquivo->commits (build/cache/busca)
│   ├── repo_setup.py        ← clonagem opcional do repo do kernel
│   ├── dataset_io.py        ← leitura tolerante a falhas dos parquet
│   ├── engine.py            ← comparação patch<->commit (roda nos workers)
│   ├── pipeline.py          ← orquestra dataset -> Pool -> CSV de saída
│   └── pasta/                ← motor de comparação vendorizado do PaStA
│       ├── patch_evaluation.py
│       ├── util.py
│       └── repository/       ← Diff, MessageDiff, Repository (pygit2)
└── tests/                   ← testes unitários (config, índice de commits)
```

Cada módulo tem uma única responsabilidade: `config.py` nunca sabe nada
sobre parquet, `dataset_io.py` nunca sabe nada sobre git, `engine.py`
nunca abre um Pool. `pipeline.py` é o único lugar que conhece todas as
peças e as conecta.

### O que é `pasta/`

É um subconjunto vendorizado do PaStA original (`pypasta`), mantendo os
cabeçalhos de copyright/licença (GNU GPLv2, OTH Regensburg / Ralf
Ramsauer). Só o necessário para comparar um patch com um commit
candidato — não inclui `Clustering.py` nem `PatchStack.py`, que fazem
parte de outro fluxo de trabalho do PaStA. Os nomes de arquivo foram
normalizados para `snake_case` para ficar consistente com o resto do
projeto; o conteúdo lógico não foi alterado.

## Como usar

Requer [uv](https://docs.astral.sh/uv/) e um clone do repositório do
kernel Linux (não este projeto) — que pode ser feito manualmente ou
automaticamente, veja abaixo.

```bash
# 1. Copie e ajuste a configuração
make config              # copia example_config.toml -> config.toml
$EDITOR config.toml       # ajuste repo_path, dataset_root, list_name...

# 2. Rode o pipeline
make run                  # usa uv se disponível, senão constrói/roda via container

# ou diretamente:
uv sync
uv run lkml-ground-truth --config config.toml
```

### Clonar o repositório do kernel

Você tem duas opções, controladas por `[repo] auto_clone` em
`config.toml`:

- **Manual (padrão, `auto_clone = false`)** — como sempre foi: você
  clona o kernel na mão (`git clone https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git`)
  e aponta `paths.repo_path` pra ele. Se o caminho não existir quando o
  pipeline rodar, você recebe um erro explicando exatamente o que fazer.
- **Automático (`auto_clone = true`)** — o pipeline clona sozinho para
  `paths.repo_path`, caso ele ainda não exista, antes de começar a
  processar. Rodar de novo depois é instantâneo: se o repo já existe,
  o clone é pulado.

Como o clone completo do kernel tem décadas de histórico (dezenas de
GB), dá pra limitar a um período com `[repo] since = "2020-01-01"`
(clone raso via `git clone --shallow-since`) — bem mais rápido e leve
quando você só precisa casar patches recentes. Só preste atenção pra
essa data cobrir toda a janela que `matching.days_before` /
`matching.days_after` pode precisar (candidatos fora do histórico
clonado simplesmente não são encontrados).

Pra clonar separado, sem rodar o pipeline inteiro junto (por exemplo,
deixar clonando em background enquanto ajusta o resto da config):

```bash
make repo                                   # clona mesmo com auto_clone=false
# ou:
uv run lkml-ground-truth clone-repo         # respeita auto_clone
uv run lkml-ground-truth clone-repo --force  # ignora o toggle
```

`list_name = "all"` em `config.toml` processa todas as listas
encontradas em `dataset_root`, uma de cada vez, cada uma gerando seu
próprio `output/matches_<lista>.csv`.

## Configuração (`config.toml`)

Única fonte de configuração do projeto — não é necessário editar nenhum
outro arquivo para ajustar caminhos, paralelismo ou thresholds:

- **`[repo]`** — clonagem automática opcional do kernel (`auto_clone`),
  URL de clone e, opcionalmente, um período (`since`) para um clone
  raso. Ver [Clonar o repositório do kernel](#clonar-o-repositório-do-kernel).
- **`[paths]`** — repositório git do Linux, raiz do dataset, lista a
  processar, caminho de saída e cache do índice.
- **`[performance]`** — número de processos paralelos, tamanho de chunk
  do `multiprocessing.Pool`, frequência de log de progresso e se o
  índice deve ser reconstruído do zero.
- **`[matching]`** — janela de tempo (dias antes/depois do envio do
  e-mail) para buscar candidatos, e os thresholds do motor de
  comparação do PaStA (`autoaccept`, `interactive`, etc.).

Veja `example_config.toml` para a referência completa, comentada.

## Saída

Um CSV por lista processada, com uma linha por e-mail de patch:

| coluna               | descrição                                             |
|----------------------|--------------------------------------------------------|
| `message_id`         | Message-ID do e-mail                                    |
| `best_commit`        | hash do commit com maior score, ou vazio se nenhum       |
| `score`              | score combinado (mensagem + diff), 0.0–1.0               |
| `is_match`           | `score >= matching.interactive`                          |
| `is_confident_match` | `score >= matching.autoaccept`                           |
| `error`              | mensagem de erro, se a linha falhou ao processar         |

## Desenvolvimento

```bash
uv sync --all-extras --dev
make lint     # ruff check
make fmt      # ruff format
make test     # nox -> pytest com coverage
```

Hooks de pre-commit (whitespace, TOML/YAML válido, ruff) estão em
`.pre-commit-config.yaml`; rode `pre-commit install` uma vez para
ativá-los localmente.

## Licença

O código próprio deste projeto segue a licença em `LICENSE`. O
subpacote `src/lkml_ground_truth/pasta/` é vendorizado do PaStA e
permanece sob GNU GPLv2, com atribuição original preservada em cada
arquivo.
