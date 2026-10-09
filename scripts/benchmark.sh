#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."

real=false
case "${1:-}" in
  --report)
    uv run python -m scm_ml.benchmark.report
    uv run python -m scm_ml.benchmark.figure
    exit 0
    ;;
  --real) real=true ;;
  "") ;;
  *) echo "usage: $0 [--real|--report]" >&2; exit 2 ;;
esac

step() { echo; echo "== $*"; }

step "synthetic world"
uv run python -m scm_ml.synthetic --out data/synthetic --seed 42
step "forecast: baselines vs LightGBM (synthetic)"
uv run python -m scm_ml.forecast --source synthetic
if $real; then
  step "real dataset and forecast"
  uv run python -m scm_ml.realdata
  uv run python -m scm_ml.forecast --source real
fi
step "sourcing, procurement and allocation"
uv run python -m scm_ml.optimization
step "scenarios"
uv run python -m scm_ml.scenario
step "RAG"
uv run python -m scm_ml.knowledge --embedder fastembed
uv run python -m scm_ml.knowledge --embedder hashing
step "agent"
uv run python -m scm_ml.agent
step "feedback loop"
uv run python -m scm_ml.feedback evaluate
uv run python -m scm_ml.feedback retrain
step "report"
uv run python -m scm_ml.benchmark.report
uv run python -m scm_ml.benchmark.figure
