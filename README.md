# LKML Ground Truth

LKML Ground Truth links Linux kernel patch emails from a MailingListsHeritage (MLH) Parquet dataset to the commits that integrate them into a Linux Git repository. It uses a vendored subset of [PaStA](https://github.com/lfd/PaStA) for patch comparison and a persistent file-to-commit index for candidate discovery.

## Outputs

The matching pipeline writes one CSV per mailing list. Each processed patch has `message_id`, `best_commit`, `commit_date`, similarity `score`, decision flags, and an optional `error`. `make enrich` persists the results as partitioned Parquet data. `commit_date` is the Git committer timestamp in ISO 8601 format.

## Layout

| Path | Purpose |
| --- | --- |
| `src/lkml_ground_truth/` | Installable package and CLI. |
| `src/lkml_ground_truth/analysis/` | Fixed Polars analyses and manual DataFusion SQL. |
| `src/lkml_ground_truth/pasta/` | Minimal vendored PaStA engine. |
| `scripts/` | Stand-alone export, integration, and review utilities. |
| `tests/` | Automated tests. |
| `docs/` | Architecture, configuration, analysis, and development guides. |
| `output/` | Generated artifacts; ignored by Git. |

## Quick start

```bash
uv sync --locked --group dev
make config
# Edit config.toml: set paths.dataset_root and paths.repo_path.
make repo       # optional when repo_path is already a Linux clone
make run
make enrich
make analysis ANALYSIS=dataset_coverage LIST=all
```

## Commands

| Command | Description |
| --- | --- |
| `make config` | Create `config.toml` from the example. |
| `make repo` | Clone or validate the Linux repository. |
| `make run` | Run patch-email to commit matching. |
| `make enrich` | Write enriched Parquet results. |
| `make analysis ANALYSIS=<name> LIST=<name>` | Export a fixed Polars report. |
| `make -C src/lkml_ground_truth/analysis query` | Open the manual DataFusion SQL REPL. |
| `make test` / `make lint` | Run tests / static checks. |

Read [Architecture](docs/architecture.md), [Configuration](docs/configuration.md), [Analysis](docs/analysis.md), and [Development](docs/development.md) for complete guidance.

## License

The project license is in [LICENSE](LICENSE). The vendored `pasta/` subpackage retains its upstream PaStA copyright and GPLv2 notices.
