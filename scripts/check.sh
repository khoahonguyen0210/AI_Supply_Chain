#!/usr/bin/env bash
# Deterministic Python quality gate: tests, lint, type check.
set -euo pipefail
cd "$(dirname "$0")/.."
uv run pytest
uv run ruff check .
uv run mypy src ml/src ml/tests
