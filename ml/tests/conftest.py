import pytest

from scm_ml.agent.context import PlanningContext, build_planning_context
from scm_ml.forecast.model import ModelConfig, train_forecaster
from scm_ml.forecast.panel import default_split, panel_from_world
from scm_ml.forecast.uncertainty import QUANTILES, calibrate
from scm_ml.service.forecasting import ForecastService
from scm_ml.synthetic import SyntheticConfig, SyntheticWorld, generate_world

FAST_MODEL = ModelConfig(max_rounds=40, early_stopping_rounds=10)
SMALL_WORLD = SyntheticConfig(
    seed=31, n_skus=8, n_suppliers=7, n_weeks=70, target_sales_orders=4_000
)


@pytest.fixture(scope="session")
def small_world() -> SyntheticWorld:
    return generate_world(SMALL_WORLD)


@pytest.fixture(scope="session")
def small_service(small_world: SyntheticWorld) -> ForecastService:
    panel = panel_from_world(small_world)
    split = default_split(panel)
    model = calibrate(train_forecaster(panel, split, FAST_MODEL, QUANTILES), panel, split, 8)
    return ForecastService(model, panel)


@pytest.fixture(scope="session")
def small_context(small_world: SyntheticWorld, small_service: ForecastService) -> PlanningContext:
    return build_planning_context(small_world, small_service)
