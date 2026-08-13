# lkml-ground-truth

Builds a patch commit *ground truth* for Linux kernel mailing lists: matches patch emails (a dataset in the format produced by [MailinglistsHeritage](https://github.com/) - parquet partitioned by list=<name>/`) with the corresponding commits in the Linux git repository, reusing the comparison engine from [PaStA](https://github.com/lfd/PaStA) (Patch Stack Analysis).

## Overview

The naive approach - running git log once per patch means hundreds of thousands of subprocesses on large datasets, each paying the git startup cost and scanning the whole history. That is what made the pipeline run for 20h+ without finishing a single list.

instead, the project builds a *file → commits index* in a single pass (git log --name-only') over the entire repository history, cached to disk. Per-patch candidate lookup becomes an in-memory binary search (bisect), with no subprocess - roughly 1000x faster per lookup.

## Prerequisites

### Container Runtime (Required)

- Podman, or
- Docker

### Native Development (Optional) 
- Python 3.12+
- [uv] (https://docs.astral.sh/uv/) package manager
- A clone of the Linux kernel repository (see below) - this can be done 
  manually or automatically.

## Installation

### Using Devbox (Recommended)

```bash
devbox shell
```

This sets up Python, uv, and all required dependencies automatically, and 
registers the pre-commit hooks.

### Manual Setup

```bash
# Install uv if not already installed
curl -LsSf https://astral.sh/uv/install.sh

# Install dependencies (from the committed uv.lock) uv sync --locked
uv sync --locked
```

## Usage

```bash
# 1. Copy and adjust the configuration
make config # copies example_config.toml -> config.toml
$EDITOR config.toml # set repo_path, dataset root, list name...

# 2. Run the pipeline make run
make run # uses uv if available, otherwise builds/runs via container

# or directly:
uv run lkml ground-truth --config config.tomi
```

### Cloning the kernel repository

Two options, controlled by `[repo] auto_clone` in `config.toml`":

- **Manual (default, auto_clone = false)** - you clone the kernel
  yourself (git clone https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git)
  and point `paths.repo_path` at it. If the path does not exist when the
  pipeline runs, you get an error explaining exactly what to do.
- **Automatic (`auto_clone = true`)** - the pipeline clones into 
  `paths.repo_path` itself, if it does not exist yet, before processing.
  Re-running afterwards is instant: if the repo already exists, the clone is 
  skipped.

Since a full kernel clone spans decades of history (tens of GB), you can limit it to a time window with `[repo] since = "2020-01-01"` (a shallow clone via `git clone --shallow-since`) - much faster and lighter when you only need to maich recent patches. Just make sure that date covers the whole window `matching.days before` / `matching.days_after` might need (candidates outside the cloned history simply are not found).

To clone separately, without running the whole pipeline (e.g. leaving it cloning in the background while you adjust the rest of the config):

```bash
make repo # clones even with auto_clone = false
# or
uv run lkml-ground-truth clone-repo # respects auto_clone
uv run lkml-ground-truth clone-repo --force # ignores the toggle
```

### Running in a container with external data

When running via container (no local uv), the project directory is mounted at `/app`. To make an external dataset or kernel clone visible inside the container, pass extra bind mounts - they are mounted at the same path so absolute paths in `config.toml` stay valid:

```bash
make run DATASET_VOLUME=/data/mlh/dataset REPO_VOLUME=/data/linux/repo
```

## Configuration (`config.toml`)

The single source of configuration for the project - no other file needs editing to adjust paths, parallelism or thresholds:

- **`[repo]`** - optional automatic kernel cloning (`auto_clone`), clone URL
  and, optionally, a time window (`since`) for a shallow clone.
- **[paths]** - Linux git repository, dataset root, list to process, output path and index cache.
- **[performance]** - number of parallel processes, `multiprocessing.Pool` chunk size, progress log frequency and whether the index should be rebuilt from scratch.
- **[matching]** time window (days before/after the email date) to for candidates, and the PaStA comparison-engine thresholds (`autoaccept`, `interactive`, etc.)

See `example_config.toml` for the full, commented reference.

## Output

One CSV per processed list, one row per patch email:

| column                          | description               |
|---------------------------------|---------------------------|
| `message_id`                    | email Message-ID |
| `best_commit`                   | highest-scoring commit hash, or empty if none |
| `score`                         | combined score (message + diff), 0.0–1.0 |
| `is match`                      | score >= matching.interactive |
| `is_confident_match`            | score >= matching.autoaccept |
| `error`                         | error message, if the row failed to process  |


### Enriching the original dataset

The CSV above is the ground-truth artifact. To fold those results **back into the mailing-list dataset**, run the `enrich` step after `run`:

```bash
uv run lkml-ground-truth enrich # left-joins matches onto the parquet
```

It reads the original parquet and the match CSV, left-joins them on `message_id`, and writes a new **enriched** parquet under

`paths.enriched_root` (default `output/enriched/`), keeping the same

`list=<name>`/ layout. Every original row is preserved - emails without a patch (never processed by the pipeline) simply get null match columns. The added columns are `best_commit`, `score`, `is_match` and `is_confident_match`. The original dataset and the CSV are left untouched.

### What pasta/ is

A vendored subset of the original PaStA (`pypasta`), keeping the copyright/license headers (GNU GPLv2, OTH Regensburg / Ralf Ramsauer). Only what is needed to compare a patch with a candidate commit - it does not include `Clustering.py` nor `PatchStack.py`, which belong to another PaStA workflow. File names were normalized to `snake_case` for consistency with the rest of the project; the logical content was not changed.

## Development

```bash
uv sync --locked --all-extras --dev
make lint # ruff check
make fmt
make test
```

Pre-commit hooks (whitespace, valid TOML/YAML/JSON, ruff, typos) live in `.pre-commit-config.yaml`; run `pre-commit install` (or `prek install`) once
to enable them locally.

## Container Build

```bash
make rebuild # builds the image from Containerfile
```

## License

This project's own code follow the license in `LICENSE`. The
`src/lkml_ground_truth/pasta/` subpackage is vendored from PaStA and remains
under GNU GPLv2, with the original attribution preserved in each file