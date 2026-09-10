#!/usr/bin/env bash
# End-to-end test: PostgreSQL + Spring backend + Python engine, driven through the public API.
# Needs Docker (Testcontainers), Java 21 and a trained forecast model under ml/artifacts.
set -euo pipefail
cd "$(dirname "$0")/.."
SCM_E2E=1 uv run pytest tests/e2e -m e2e -v "$@"
