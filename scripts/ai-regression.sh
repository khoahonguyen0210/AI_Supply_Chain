#!/usr/bin/env bash
# Exits 1 on a regression; --update-baseline accepts a change.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run python -m scm_ml.regression "$@"
