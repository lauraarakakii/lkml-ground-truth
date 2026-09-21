# LKML Ground Truth

LKML Ground Truth links patch emails from a MailingListsHeritage Parquet
dataset to their corresponding commits in the Linux Git repository. It uses a
vendored subset of [PaStA](https://github.com/lfd/PaStA) for patch comparison
and a persistent file-to-commit index to avoid repeatedly scanning Git history.

## Project layout

The repository follows the component-oriented conventions used by
MLH-Archiver:

| Path | Purpose |
| --- | --- |
| `src/lkml_ground_truth/` | Pipeline package and command-line interface |
| `src/lkml_ground_truth/pasta/` | Minimal vendored PaStA comparison engine |
| `src/scripts/` | Stand-alone export, integration, and review utilities |
| `tests/` | Unit and integration tests |
| `output/` | Generated matches, enriched data, and index cache (ignored) |
| `resources/` | Optional local Linux clone and dataset mounts (ignored) |

## Quick start

```bash
devbox shell
make config
$EDITOR config.toml
make run
```

`make config` creates a local `config.toml`. Set `paths.dataset_root` to the
MLH Parser output and set `paths.repo_path` to a Linux Git clone. Alternatively,
enable `repo.auto_clone` and run `make repo` to create the clone.

## Commands

| Command | Description |
| --- | --- |
| `make` / `make run` | Run the matching pipeline |
| `make repo` | Clone or validate the Linux repository |
| `make enrich` | Join match results back into the source Parquet dataset |
| `make query SQL='SELECT ...'` | Query original and enriched Parquet data |
| `make test` | Run tests with nox |
| `make lint` | Run Ruff checks |
| `make fmt` | Format Python code with Ruff |
| `make build` | Build the fallback container image |
| `make clean` | Remove local Python test and cache artifacts |

The Makefile uses `uv` when it is available. Otherwise, `run` and `test` use a
container runtime detected through `containers.mk` (`podman` first, then
`docker`). Supply `REPO_VOLUME` and `DATASET_VOLUME` when your configuration
uses absolute external paths:

```bash
make run REPO_VOLUME=/data/linux DATASET_VOLUME=/data/mlh/dataset
```

## Configuration

`example_config.toml` documents the configuration fields. `list_name` accepts a
single partition name or `all`. Output rows contain `message_id`, `best_commit`,
`score`, `is_match`, `is_confident_match`, and an optional `error`.

## Development

```bash
uv sync --locked --group dev
make lint
make test
```

Pre-commit hooks are configured in `.pre-commit-config.yaml`. The vendored
`pasta` package retains its original PaStA copyright and GNU GPLv2 notices;
the rest of this repository follows the license in `LICENSE`.
