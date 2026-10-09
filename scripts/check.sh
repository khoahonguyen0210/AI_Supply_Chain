#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
uv run pytest
uv run ruff check .
uv run ruff format --check .
uv run mypy src ml/src ml/tests tests
