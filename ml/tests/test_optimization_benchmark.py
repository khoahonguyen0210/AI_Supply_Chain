import json
from pathlib import Path
from typing import Any

import pytest

from scm_ml.forecast.model import ModelConfig, train_forecaster
from scm_ml.forecast.panel import default_split, panel_from_world
from scm_ml.forecast.uncertainty import QUANTILES, calibrate
from scm_ml.optimization.benchmark import (
    forecast_artifact_dirs,
    run_benchmark,
    serving_warehouse,
    warehouse_demand,
)
from scm_ml.service.forecasting import ForecastService
from scm_ml.synthetic import SyntheticConfig, SyntheticWorld, generate_world

FAST = ModelConfig(max_rounds=40, early_stopping_rounds=10)
SMALL = SyntheticConfig(seed=31, n_skus=8, n_suppliers=7, n_weeks=70, target_sales_orders=4_000)


@pytest.fixture(scope="module")
def world() -> SyntheticWorld:
    return generate_world(SMALL)


@pytest.fixture(scope="module")
def result(world: SyntheticWorld, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    panel = panel_from_world(world)
    split = default_split(panel)
    model = calibrate(train_forecaster(panel, split, FAST, QUANTILES), panel, split, 8)
    out = tmp_path_factory.mktemp("bench") / "optimization.json"
    outcome = run_benchmark(world, ForecastService(model, panel), out_path=out)
    assert json.loads(out.read_text(encoding="utf-8")) == json.loads(json.dumps(outcome))
    return outcome


def test_benchmark_records_identity_and_provenance(
    result: dict[str, Any], world: SyntheticWorld
) -> None:
    assert result["dataset_id"] == panel_from_world(world).dataset_id
    assert result["forecast_model_version"]
    assert result["as_of"] == world.as_of.isoformat()
    assert {"created_at", "code_revision"} <= set(result["provenance"])
    assert set(result["cases"]) == {"base", "tight_budget"}


def test_every_method_reports_the_required_measures(result: dict[str, Any]) -> None:
    for methods in result["cases"].values():
        for name in ("heuristic_cheapest", "heuristic_weighted", "milp"):
            row = methods[name]
            assert {"objective", "fill_rate", "runtime_seconds", "constraint_violations"} <= set(
                row
            )
            assert set(row["allocation"]) == {"nearest_warehouse_rule", "milp"}


def test_optimizer_has_no_violations_and_lowest_objective(result: dict[str, Any]) -> None:
    for case, methods in result["cases"].items():
        milp = methods["milp"]
        assert milp["solver_status"] == "OPTIMAL", case
        assert milp["constraint_violations"]["count"] == 0, case
        for name in ("heuristic_cheapest", "heuristic_weighted"):
            assert milp["objective"] <= methods[name]["objective"] + 1e-6, (case, name)


def test_tight_budget_binds_the_optimizer_and_is_breached_by_heuristics(
    result: dict[str, Any],
) -> None:
    tight = result["cases"]["tight_budget"]
    assert tight["milp"]["spend"] <= tight["budget"] + 1e-6
    assert tight["milp"]["spend"] < result["cases"]["base"]["milp"]["spend"]
    for name in ("heuristic_cheapest", "heuristic_weighted"):
        assert tight[name]["constraint_violations"]["by_kind"].get("BUDGET", 0) >= 1


def test_allocation_optimizer_is_never_worse_than_the_rule(result: dict[str, Any]) -> None:
    for methods in result["cases"].values():
        for name in ("heuristic_cheapest", "heuristic_weighted", "milp"):
            allocation = methods[name]["allocation"]
            assert (
                allocation["milp"]["objective"]
                <= allocation["nearest_warehouse_rule"]["objective"] + 1e-6
            )


def test_regions_map_to_their_cheapest_warehouse(world: SyntheticWorld) -> None:
    primary = serving_warehouse(world.lanes)
    for region_id, warehouse_id in primary.items():
        costs = {
            lane.warehouse_id: lane.cost_per_unit
            for lane in world.lanes
            if lane.region_id == region_id
        }
        assert costs[warehouse_id] == min(costs.values())
    demand = warehouse_demand({("SKU-001", region): 10.0 for region in primary}, world.lanes)
    assert sum(demand.values()) == pytest.approx(10.0 * len(primary))


def test_missing_forecast_artifacts_give_an_actionable_error(
    world: SyntheticWorld, tmp_path: Path
) -> None:
    with pytest.raises(FileNotFoundError, match="scm_ml.forecast"):
        forecast_artifact_dirs(world, tmp_path)
