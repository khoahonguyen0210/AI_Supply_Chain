import json
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient

from scm_ml.feedback.actuals import (
    SIMULATED,
    simulate_deliveries,
    simulate_demand,
    simulate_inventory,
)
from scm_ml.feedback.evaluation import (
    DeliveryOutcome,
    ForecastOutcome,
    InventoryWeek,
    compare_inventory,
    delivery_performance,
    forecast_accuracy,
    inventory_outcome,
)
from scm_ml.feedback.experiment import run_feedback_experiment
from scm_ml.feedback.retraining import (
    AWAITING_APPROVAL,
    REJECTED_BY_GATE,
    PromotionError,
    PromotionGate,
    extend_panel,
    promote,
    retrain,
    serving_directories,
)
from scm_ml.forecast.model import train_forecaster
from scm_ml.forecast.panel import extends, panel_from_world
from scm_ml.service.app import create_app
from scm_ml.service.engine import build_engine
from scm_ml.service.forecasting import ForecastService
from scm_ml.synthetic import SyntheticWorld
from scm_ml.synthetic.generator import generate_world_with_future, outcome_rng

MONDAY = date(2025, 1, 6)


def test_the_world_is_unchanged_by_its_hidden_future(small_world: SyntheticWorld) -> None:
    world, future = generate_world_with_future(small_world.config)
    assert panel_from_world(world).dataset_id == panel_from_world(small_world).dataset_id
    open_orders = {po.po_id: po for po in world.purchase_orders if po.delivered_at is None}
    assert set(future.pending_deliveries) == set(open_orders)
    for po_id, (delivered_on, quantity) in future.pending_deliveries.items():
        assert delivered_on > world.as_of
        assert 0 < quantity <= open_orders[po_id].quantity


def test_simulated_demand_is_deterministic_and_continues_the_process(
    small_world: SyntheticWorld,
) -> None:
    cfg = small_world.config
    world, future = generate_world_with_future(cfg)
    first = simulate_demand(world, future, outcome_rng(cfg), 6)
    second = simulate_demand(world, future, outcome_rng(cfg), 6)
    pd.testing.assert_frame_equal(first, second)
    assert len(first) == len(world.skus) * len(world.regions) * 6
    assert sorted(set(first["week_start"])) == [world.as_of + timedelta(weeks=k) for k in range(6)]
    # same scale as the history: mean weekly units within a factor of two of the last 13 weeks
    panel = panel_from_world(world)
    recent = panel.values[:, -13:].sum() / 13
    future_mean = first["quantity"].sum() / 6
    assert 0.5 * recent < future_mean < 2.0 * recent


def test_deliveries_follow_supplier_reliability() -> None:
    orders = [DeliveryOutcome(f"PO-{i}", "S", 100, MONDAY) for i in range(50)]
    rng = np.random.default_rng(1)
    reliable = simulate_deliveries(orders, {"S": 1.0}, rng)
    assert all(d.delivered_on == MONDAY and d.delivered_quantity == 100 for d in reliable)
    unreliable = simulate_deliveries(orders, {"S": 0.0}, rng)
    delays = [(d.delivered_on - MONDAY).days for d in unreliable if d.delivered_on]
    assert min(delays) >= 1 and max(delays) <= 10
    assert all(70 <= (d.delivered_quantity or 0) <= 100 for d in unreliable)


def test_inventory_serves_demand_from_stock_and_loses_the_rest(
    small_world: SyntheticWorld,
) -> None:
    position = small_world.inventory[0]
    key = (position.sku_id, position.warehouse_id)
    weeks = [small_world.as_of, small_world.as_of + timedelta(weeks=1)]
    demand = {(*key, weeks[0]): position.on_hand + 5.0, (*key, weeks[1]): 3.0}
    receipts = {(*key, weeks[1]): 10.0}
    rows = [
        r
        for r in simulate_inventory(small_world, weeks, demand, receipts)
        if (r.sku_id, r.warehouse_id) == key
    ]
    assert [(r.on_hand, r.unmet) for r in rows] == [(0.0, 5.0), (7.0, 0.0)]


def test_forecast_accuracy_scores_points_and_intervals() -> None:
    rows = [
        ForecastOutcome("A", "R", MONDAY, 1, 10.0, 5.0, 15.0, 12.0),
        ForecastOutcome("A", "R", MONDAY + timedelta(weeks=1), 2, 10.0, 8.0, 9.0, 20.0),
    ]
    result = forecast_accuracy(rows)
    overall = result["overall"]
    assert overall["mae"] == 6.0 and overall["bias"] == -6.0
    assert overall["wape"] == round(12 / 32, 4)
    assert overall["coverage"] == 0.5 and overall["n"] == 2
    assert set(result["by_horizon"]) == {"1", "2"}
    point_only = forecast_accuracy([ForecastOutcome("A", "R", MONDAY, 1, 1.0, None, None, 2.0)])
    assert "coverage" not in point_only["overall"]
    assert forecast_accuracy([]) == {"overall": None, "by_horizon": {}}


def test_delivery_performance_against_promises() -> None:
    rows = [
        DeliveryOutcome("P1", "S1", 100, MONDAY, MONDAY, 100),
        DeliveryOutcome("P2", "S1", 100, MONDAY, MONDAY + timedelta(days=4), 80),
        DeliveryOutcome("P3", "S2", 50, MONDAY),  # not delivered yet
    ]
    result = delivery_performance(rows, {"S1": 0.9, "S2": 0.8})
    overall = result["overall"]
    assert (overall["orders"], overall["delivered"], overall["pending"]) == (3, 2, 1)
    assert overall["on_time_rate"] == 0.5 and overall["in_full_rate"] == 0.5
    assert overall["unit_fill_rate"] == 0.9 and overall["mean_delay_days"] == 2.0
    s1 = result["by_supplier"]["S1"]
    assert s1["promised_on_time_rate"] == 0.9 and s1["on_time_gap"] == -0.4
    assert result["by_supplier"]["S2"]["on_time_rate"] is None


def test_inventory_outcome_and_planned_versus_actual() -> None:
    week2 = MONDAY + timedelta(weeks=1)
    planned = [
        InventoryWeek("A", "W", MONDAY, 10.0, 0.0, 5.0),
        InventoryWeek("A", "W", week2, 5.0, 0.0, 5.0),
    ]
    actual = [
        InventoryWeek("A", "W", MONDAY, 0.0, 2.0, 17.0),
        InventoryWeek("A", "W", week2, 0.0, 4.0, 4.0),
    ]
    outcome = inventory_outcome(actual)
    assert outcome["stockout_cell_weeks"] == 2 and outcome["cells_with_stockout"] == 1
    assert outcome["fill_rate"] == round(1 - 6 / 21, 4)
    comparison = compare_inventory(planned, actual)
    assert comparison["unexpected_stockout_cell_weeks"] == 2
    assert comparison["ending_on_hand_mae"] == 5.0 and comparison["ending_on_hand_bias"] == -5.0
    unknown_demand = inventory_outcome([InventoryWeek("A", "W", MONDAY, 3.0, 1.0)])
    assert unknown_demand["fill_rate"] is None and unknown_demand["unmet_units"] == 1.0


def test_feedback_experiment_replays_the_decision(
    small_world: SyntheticWorld, small_service: ForecastService, tmp_path: Path
) -> None:
    result = run_feedback_experiment(
        small_service, small_world.config, out_dir=tmp_path, experiment_path=None
    )
    assert result["actuals_source"] == SIMULATED
    assert result["forecast"]["model"]["overall"]["n"] == len(small_service.history.series) * 8
    assert 0 <= result["forecast"]["model"]["overall"]["coverage"] <= 1
    decision = result["decision"]
    assert decision["approval"].startswith("SIMULATED")
    plan = result["deliveries"]["plan_orders"]["overall"]
    assert plan["orders"] == decision["purchase_orders"] and plan["pending"] == 0
    for path in ("planned", "actual"):
        assert 0 <= result["inventory"][path]["fill_rate"] <= 1
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["files_sha256"] == result["actuals"]["files_sha256"]
    demand = pd.read_csv(tmp_path / "demand_actuals.csv")
    assert set(demand["source"]) == {SIMULATED}


def _actuals(world: SyntheticWorld, weeks: int) -> pd.DataFrame:
    _, future = generate_world_with_future(world.config)
    return simulate_demand(world, future, outcome_rng(world.config), weeks)


def test_extend_panel_appends_weeks_and_rejects_bad_actuals(
    small_world: SyntheticWorld,
) -> None:
    history = panel_from_world(small_world)
    actuals = _actuals(small_world, 3)
    extended = extend_panel(history, actuals)
    assert len(extended.weeks) == len(history.weeks) + 3 and extends(extended, history)
    assert extended.values[:, -3:].sum() == actuals["quantity"].sum()
    with pytest.raises(ValueError, match="consecutive"):
        extend_panel(history, actuals[actuals["week_start"] != small_world.as_of])
    with pytest.raises(ValueError, match="without history"):
        extend_panel(
            history, pd.concat([actuals.iloc[1:], actuals.head(1).assign(sku_id="SKU-999")])
        )
    with pytest.raises(ValueError, match="duplicate"):
        extend_panel(history, pd.concat([actuals, actuals.head(1)]))


def test_the_gate_needs_a_better_mae_and_calibrated_intervals() -> None:
    gate = PromotionGate(min_mae_improvement=0.05)
    current = {"mae": 10.0, "coverage": 0.8}
    assert gate.check(current, {"mae": 9.0, "coverage": 0.82}) == []
    assert len(gate.check(current, {"mae": 9.8, "coverage": 0.82})) == 1
    assert len(gate.check(current, {"mae": 9.0, "coverage": 0.5})) == 1


@pytest.fixture(scope="module")
def candidate(
    small_world: SyntheticWorld, small_service: ForecastService, tmp_path_factory: Any
) -> tuple[Path, Path, dict[str, Any]]:
    root = tmp_path_factory.mktemp("artifacts")
    report = retrain(
        small_service.model,
        small_service.history,
        _actuals(small_world, 6),
        actuals_label=SIMULATED,
        actuals_sha256="0" * 64,
        holdout_weeks=2,
        config=small_service.model.config,
        root=root,
        train=train_forecaster,
    )
    path = root / "report.json"
    path.write_text(json.dumps(report), encoding="utf-8")
    return root, path, report


def test_retraining_scores_both_models_on_unseen_weeks(
    candidate: tuple[Path, Path, dict[str, Any]], small_service: ForecastService
) -> None:
    root, _, report = candidate
    assert report["status"] in {AWAITING_APPROVAL, REJECTED_BY_GATE}
    assert report["status"] == (AWAITING_APPROVAL if report["gate"]["passed"] else REJECTED_BY_GATE)
    assert report["current"]["model_version"] == small_service.model.version
    assert report["candidate"]["model_version"] != small_service.model.version
    history_end = small_service.history.weeks[-1]
    assert report["holdout"]["weeks"][0] == (history_end + timedelta(weeks=5)).isoformat()
    assert report["candidate"]["split"]["test_start"] < report["holdout"]["weeks"][0]
    assert (root / report["candidate"]["artifact_dir"] / "model" / "meta.json").exists()
    assert serving_directories(root) is None  # retraining never deploys


def _with_gate(path: Path, passed: bool, tmp_path: Path) -> Path:
    report = json.loads(path.read_text(encoding="utf-8"))
    report["gate"].update(passed=passed, reasons=[] if passed else ["worse"])
    report["status"] = AWAITING_APPROVAL if passed else REJECTED_BY_GATE
    out = tmp_path / f"report-{passed}.json"
    out.write_text(json.dumps(report), encoding="utf-8")
    return out


def test_promotion_needs_a_passed_gate_and_a_named_approver(
    candidate: tuple[Path, Path, dict[str, Any]], tmp_path: Path
) -> None:
    root, path, report = candidate
    with pytest.raises(PromotionError, match="gate"):
        promote(_with_gate(path, False, tmp_path), "mia", root=root)
    passing = _with_gate(path, True, tmp_path)
    with pytest.raises(PromotionError, match="approver"):
        promote(passing, "  ", root=root)
    assert serving_directories(root) is None

    entry = promote(passing, "mia", root=root, note="reviewed")
    assert entry["approved_by"] == "mia"
    assert entry["model_version"] == report["candidate"]["model_version"]
    served = serving_directories(root)
    assert served is not None and served[0].name == "model"
    log = (root / "promotions.jsonl").read_text(encoding="utf-8").splitlines()
    assert len(log) == 1 and json.loads(log[0])["approved_by"] == "mia"


def test_promotion_refuses_artifacts_that_changed_after_evaluation(
    candidate: tuple[Path, Path, dict[str, Any]], tmp_path: Path
) -> None:
    root, path, _ = candidate
    report = json.loads(_with_gate(path, True, tmp_path).read_text(encoding="utf-8"))
    report["candidate"]["model_version"] = "lgbm-other"
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(report), encoding="utf-8")
    with pytest.raises(PromotionError, match="not the one that was evaluated"):
        promote(tampered, "mia", root=root)


def test_a_promoted_model_can_be_served_by_the_engine(
    candidate: tuple[Path, Path, dict[str, Any]], small_world: SyntheticWorld
) -> None:
    root, _, report = candidate
    model_dir = root / report["candidate"]["artifact_dir"] / "model"
    service = ForecastService.from_directories(model_dir, model_dir.parent / "dataset")
    assert extends(service.history, panel_from_world(small_world))
    build_engine(small_world, service)  # accepts history that extends the world's


@pytest.fixture(scope="module")
def client(small_world: SyntheticWorld, small_service: ForecastService) -> Iterator[TestClient]:
    app = create_app(small_service, build_engine(small_world, small_service), require_token=False)
    with TestClient(app) as test_client:
        yield test_client


ACTOR = {"userId": "pat", "role": "planner"}


def test_forecast_snapshot_covers_every_region_with_demand(
    client: TestClient, small_world: SyntheticWorld, small_service: ForecastService
) -> None:
    response = client.post(
        "/v1/outcomes/forecast-snapshot",
        json={
            "schemaVersion": "1",
            "actor": ACTOR,
            "skuIds": ["SKU-001"],
            "asOf": small_world.as_of.isoformat(),
            "horizonWeeks": 3,
        },
    )
    assert response.status_code == 200
    data = response.json()["data"]
    regions = [r for s, r in small_service.history.series if s == "SKU-001"]
    assert len(data["points"]) == 3 * len(regions)
    assert data["modelVersion"] == small_service.model.version
    assert {"skuId", "regionId", "weekStart", "horizon", "point", "lower", "upper"} <= set(
        data["points"][0]
    )
    unknown = client.post(
        "/v1/outcomes/forecast-snapshot",
        json={"actor": ACTOR, "skuIds": ["SKU-999"], "asOf": small_world.as_of.isoformat()},
    )
    assert unknown.status_code == 404 and unknown.json()["code"] == "UNKNOWN_SKU"


def test_recorded_outcomes_are_scored_by_the_engine(client: TestClient) -> None:
    body = {
        "schemaVersion": "1",
        "actor": ACTOR,
        "forecasts": [
            {
                "skuId": "SKU-001",
                "regionId": "R1",
                "weekStart": "2025-01-06",
                "horizon": 1,
                "point": 10,
                "lower": 5,
                "upper": 15,
            },
            {
                "skuId": "SKU-001",
                "regionId": "R1",
                "weekStart": "2025-01-13",
                "horizon": 2,
                "point": 10,
                "lower": 5,
                "upper": 15,
            },
        ],
        "demand": [
            {"skuId": "SKU-001", "regionId": "R1", "weekStart": "2025-01-06", "quantity": 12}
        ],
        "deliveries": [
            {
                "poId": "P1",
                "supplierId": "SUP-1",
                "orderedQuantity": 100,
                "expectedDelivery": "2025-01-06",
                "deliveredOn": "2025-01-08",
                "deliveredQuantity": 100,
                "promisedReliability": 0.9,
            }
        ],
        "inventory": [
            {"skuId": "SKU-001", "warehouseId": "W1", "weekStart": "2025-01-06", "onHand": 0}
        ],
    }
    response = client.post("/v1/outcomes/evaluate", json=body)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["forecast"]["overall"]["mae"] == 2.0
    assert data["forecast"]["awaitingActuals"] == 1
    assert data["deliveries"]["bySupplier"]["SUP-1"]["onTimeRate"] == 0.0
    assert data["inventory"]["cellWeeks"] == 1
    bad = client.post("/v1/outcomes/evaluate", json={**body, "demand": [{"skuId": "X"}]})
    assert bad.status_code == 422
