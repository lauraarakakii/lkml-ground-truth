#!/usr/bin/env bash
set -euo pipefail

uv sync --locked --all-extras --dev
prek install