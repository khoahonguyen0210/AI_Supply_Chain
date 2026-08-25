from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest
from fastapi.testclient import TestClient

from scm_ml.forecast.inference import ForecastError, forecast_series
from scm_ml.forecast.model import ForecastModel, ModelConfig, train_forecaster
from scm_ml.forecast.panel import ForecastPanel, default_split, panel_from_world
from scm_ml.forecast.uncertainty import QUANTILES, calibrate
from scm_ml.service.app import create_app
from scm_ml.service.contracts import ForecastResponse
from scm_ml.service.engine import build_engine
from scm_ml.service.export_contracts import CONTRACT_DIR, contract_files, example_response
from scm_ml.service.forecasting import ForecastService
from scm_ml.synthetic import SyntheticConfig, SyntheticWorld, generate_world

FAST = ModelConfig(max_rounds=40, early_stopping_rounds=10)


@pytest.fixture(scope="module")
def world() -> SyntheticWorld:
    cfg = SyntheticConfig(seed=31, n_skus=8, n_suppliers=7, n_weeks=70, target_sales_orders=4_000)
    return generate_world(cfg)


@pytest.fixture(scope="module")
def panel(world: SyntheticWorld) -> ForecastPanel:
    return panel_from_world(world)


@pytest.fixture(scope="module")
def model(panel: ForecastPanel) -> ForecastModel:
    split = default_split(panel)
    return calibrate(train_forecaster(panel, split, FAST, QUANTILES), panel, split, 8)


@pytest.fixture(scope="module")
def client(world: SyntheticWorld, panel: ForecastPanel, model: ForecastModel) -> TestClient:
    service = ForecastService(model, panel)
    with TestClient(
        create_app(service, build_engine(world, service), require_token=False)
    ) as test_client:
        return test_client


def _body(panel: ForecastPanel, **overrides: object) -> dict[str, object]:
    sku, region = panel.series[0]
    first_unseen = panel.weeks[-1] + timedelta(weeks=1)
    return {
        "schemaVersion": "1",
        "skuId": sku,
        "regionId": region,
        "asOf": first_unseen.isoformat(),
        "horizonWeeks": 8,
        **overrides,
    }


def test_forecast_returns_versioned_camel_case_contract(
    client: TestClient, panel: ForecastPanel
) -> None:
    response = client.post("/v1/forecast", json=_body(panel))
    assert response.status_code == 200
    payload = response.json()
    assert payload["schemaVersion"] == "1"
    assert payload["intervalLevel"] == pytest.approx(0.8)
    assert payload["modelVersion"].startswith("lgbm-") and payload["datasetId"] == panel.dataset_id
    ForecastResponse.model_validate(payload)  # round-trips through the typed contract
    points = payload["points"]
    assert [p["horizon"] for p in points] == list(range(1, 9))
    assert points[0]["weekStart"] == (panel.weeks[-1] + timedelta(weeks=1)).isoformat()
    assert all(p["lower"] <= p["point"] <= p["upper"] for p in points)


def test_horizon_is_respected(client: TestClient, panel: ForecastPanel) -> None:
    payload = client.post("/v1/forecast", json=_body(panel, horizonWeeks=3)).json()
    assert len(payload["points"]) == 3


@pytest.mark.parametrize(
    ("overrides", "status", "code"),
    [
        ({"skuId": "NOPE"}, 404, "UNKNOWN_SERIES"),
        ({"asOf": "2030-01-07"}, 409, "HISTORY_TOO_SHORT"),
        ({"asOf": "2023-02-06"}, 409, "HISTORY_TOO_SHORT"),
        ({"asOf": "2024-05-02"}, 422, "INVALID_AS_OF"),
        ({"horizonWeeks": 9}, 422, "VALIDATION_FAILED"),
        ({"schemaVersion": "2"}, 422, "VALIDATION_FAILED"),
        ({"unexpected": 1}, 422, "VALIDATION_FAILED"),
    ],
)
def test_errors_are_structured(
    client: TestClient, panel: ForecastPanel, overrides: dict[str, object], status: int, code: str
) -> None:
    response = client.post("/v1/forecast", json=_body(panel, **overrides))
    assert response.status_code == status
    assert response.json()["code"] == code
    assert response.json()["message"]


def test_health_and_model_info(client: TestClient, model: ForecastModel) -> None:
    assert client.get("/health").json() == {"status": "UP", "service": "scm-ml"}
    info = client.get("/v1/model").json()
    assert info["horizons"] == 8 and info["modelVersion"] == model.version


def test_forecast_uses_only_history_before_as_of(
    panel: ForecastPanel, model: ForecastModel
) -> None:
    as_of = panel.weeks[50]
    sku, region = panel.series[0]
    clean = forecast_series(model, panel, sku, region, as_of, 8)
    future_destroyed = panel.values.copy()
    future_destroyed[:, 50:] = 1e6
    dirty = forecast_series(model, replace(panel, values=future_destroyed), sku, region, as_of, 8)
    np.testing.assert_allclose(dirty.point, clean.point)
    np.testing.assert_allclose(dirty.upper, clean.upper)


def test_inference_rejects_bad_requests(panel: ForecastPanel, model: ForecastModel) -> None:
    sku, region = panel.series[0]
    with pytest.raises(ForecastError) as excinfo:
        forecast_series(model, panel, sku, region, date(2023, 1, 9), 4)
    assert excinfo.value.code == "HISTORY_TOO_SHORT"


def test_service_rejects_mismatched_history(panel: ForecastPanel, model: ForecastModel) -> None:
    other = replace(panel, values=panel.values + 1)
    with pytest.raises(ValueError, match="trained on"):
        ForecastService(model, other)


def test_committed_contract_files_are_current() -> None:
    for name, expected in contract_files().items():
        committed = (CONTRACT_DIR / name).read_text(encoding="utf-8")
        assert committed == expected, (
            f"{name} is stale: run `python -m scm_ml.service.export_contracts`"
        )


def test_example_response_matches_schema_version() -> None:
    example = example_response()
    assert example.schema_version == "1"
    assert Path(CONTRACT_DIR / "forecast-response-v1.example.json").exists()
