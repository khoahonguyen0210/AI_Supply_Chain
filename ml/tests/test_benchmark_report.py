from __future__ import annotations

import json
import shutil
from pathlib import Path

from scm_ml.benchmark.report import NOT_MEASURED, main, render

EXPERIMENTS = Path(__file__).resolve().parents[1] / "experiments"


def test_missing_artifacts_are_reported_not_estimated(tmp_path: Path) -> None:
    text = render(tmp_path)
    for relative in (
        "forecast/synthetic.json",
        "optimization/synthetic.json",
        "scenario/synthetic.json",
        "agent/synthetic-rule-planner.json",
        "feedback/retraining-synthetic.json",
        "systems/api-latency.json",
        "systems/worker-scaling.json",
    ):
        assert f"{NOT_MEASURED}: `ml/experiments/{relative}` does not exist." in text


def test_report_quotes_the_saved_artifacts(tmp_path: Path) -> None:
    text = render(EXPERIMENTS)
    forecast = json.loads((EXPERIMENTS / "forecast/synthetic.json").read_text(encoding="utf-8"))
    mae = forecast["model"]["test"]["overall"]["mae"]
    assert f"{mae:,.3f}" in text
    assert forecast["provenance"]["code_revision"] in text

    agent = json.loads(
        (EXPERIMENTS / "agent/synthetic-rule-planner.json").read_text(encoding="utf-8")
    )
    assert f"{agent['by_split']['holdout']['workflow_success']:,.3f}" in text
    for section in (
        "## Forecast",
        "## Sourcing",
        "## Inventory",
        "## Scenarios",
        "## RAG",
        "## Agent",
    ):
        assert section in text


def test_report_is_deterministic_and_written(tmp_path: Path) -> None:
    root = tmp_path / "experiments"
    shutil.copytree(EXPERIMENTS, root)
    out = tmp_path / "benchmarks.md"
    assert main(["--experiments", str(root), "--out", str(out)]) == 0
    assert out.read_text(encoding="utf-8") == render(root)


def test_figure_is_drawn_from_the_artifacts(tmp_path: Path) -> None:
    from scm_ml.benchmark.figure import render as draw

    svg = draw(EXPERIMENTS)
    forecast = json.loads((EXPERIMENTS / "forecast/synthetic.json").read_text(encoding="utf-8"))
    ref = forecast["baselines"][forecast["selected_baseline"]]["test"]["overall"]["mae"]
    mae = forecast["model"]["test"]["overall"]["mae"]
    assert f"{100 * (1 - mae / ref):.0f}%" in svg
    assert svg.count('class="tile"') == 4
    assert draw(tmp_path).count('class="tile"') == 0  # no artifacts, no tiles
