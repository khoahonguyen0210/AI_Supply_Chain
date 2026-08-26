#!/usr/bin/env bash
# AI regression suite: fixed RAG and agent cases against ml/configs/ai-regression-baseline.json.
# Offline and deterministic; exits 1 on a regression. Pass --update-baseline to accept a change.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run python -m scm_ml.regression "$@"
