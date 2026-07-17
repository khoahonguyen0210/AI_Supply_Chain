import json
from pathlib import Path
from typing import Any

import pytest

from scm_common.domain import ScenarioType
from scm_ml.forecast.model import ModelConfig, train_forecaster
from scm_ml.forecast.panel import default_split, panel_from_world
from scm_ml.forecast.uncertainty import QUANTILES, calibrate
from scm_ml.optimization import ProcurementParams
from scm_ml.scenario.suite import run_suite
from scm_ml.service.forecasting import ForecastService
from scm_ml.synthetic import SyntheticConfig, generate_world

FAST = ModelConfig(max_rounds=40, early_stopping_rounds=10)
SMALL = SyntheticConfig(seed=31, n_skus=8, n_suppliers=7, n_weeks=70, target_sales_orders=4_000)


@pytest.fixture(scope="module")
def outcome(tmp_path_factory: pytest.TempPathFactory) -> tuple[dict[str, Any], Path]:
    world = generate_world(SMALL)
    panel = panel_from_world(world)
    split = default_split(panel)
    model = calibrate(train_forecaster(panel, split, FAST, QUANTILES), panel, split, 8)
    out = tmp_path_factory.mktemp("scenario") / "suite.json"
    return run_suite(world, ForecastService(model, panel), ProcurementParams(), out), out


def test_suite_covers_every_scenario_type_and_records_identity(
    outcome: tuple[dict[str, Any], Path],
) -> None:
    result, out = outcome
    assert {s["scenario_type"] for s in result["scenarios"]} == {t.value for t in ScenarioType}
    assert result["dataset_id"] and result["forecast_model_version"]
    assert {"created_at", "code_revision"} <= set(result["provenance"])
    assert json.loads(out.read_text(encoding="utf-8")) == json.loads(json.dumps(result))


def test_every_scenario_reports_the_required_comparison_fields(
    outcome: tuple[dict[str, Any], Path],
) -> None:
    result, _ = outcome
    required = {
        "objective_delta_response",
        "service_level_delta_response",
        "baseline_binding",
        "response_binding",
        "changed_allocations",
        "resilience_cost",
        "changes",
    }
    for scenario in result["scenarios"]:
        assert required <= set(scenario)
        assert scenario["changes"], scenario["scenario_id"]


def test_outage_scenario_targets_the_baselines_busiest_supplier(
    outcome: tuple[dict[str, Any], Path],
) -> None:
    result, _ = outcome
    outage = next(s for s in result["scenarios"] if s["scenario_type"] == "SUPPLIER_OUTAGE")
    shifted = {s["supplier_id"]: s for s in outage["changed_allocations"]["supplier_shifts"]}
    assert shifted[result["outage_supplier"]]["response_units"] == 0
    assert shifted[result["outage_supplier"]]["baseline_units"] > 0
