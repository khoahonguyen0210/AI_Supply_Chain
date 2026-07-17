from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from scm_ml.forecast.artifacts import provenance, write_json
from scm_ml.optimization import ProcurementParams
from scm_ml.optimization.benchmark import forecast_regional_demand
from scm_ml.service.forecasting import ForecastService
from scm_ml.synthetic import SyntheticWorld

from .comparison import compare_scenario
from .contract import standard_scenarios
from .execution import DecisionResult, run_pipeline, run_scenario
from .inputs import PlanningInputs

EXPERIMENT_PATH = Path("ml/experiments/scenario/synthetic.json")
SUITE_VERSION = "1"


def busiest_supplier(result: DecisionResult) -> str:
    units: dict[str, int] = defaultdict(int)
    for line in result.procurement.lines:
        units[line.supplier_id] += line.quantity
    return max(units, key=lambda supplier_id: (units[supplier_id], supplier_id))


def run_suite(
    world: SyntheticWorld,
    service: ForecastService,
    params: ProcurementParams | None = None,
    out_path: Path | None = EXPERIMENT_PATH,
) -> dict[str, Any]:
    params = params or ProcurementParams()
    regional = forecast_regional_demand(service, world, params.horizon_weeks)
    inputs = PlanningInputs.from_world(world, regional, params)
    baseline = run_pipeline(inputs)
    outage = busiest_supplier(baseline)
    created_at = datetime.combine(world.as_of, datetime.min.time(), tzinfo=UTC)
    comparisons = [
        compare_scenario(run_scenario(inputs, scenario, baseline)).model_dump(mode="json")
        for scenario in standard_scenarios(created_at, outage)
    ]
    result: dict[str, Any] = {
        "suite_version": SUITE_VERSION,
        "dataset_id": service.history.dataset_id,
        "forecast_model_version": service.model.version,
        "as_of": world.as_of.isoformat(),
        "procurement_params": {k: getattr(params, k) for k in params.__dataclass_fields__},
        "baseline_objective": baseline.procurement.metrics.objective,
        "outage_supplier": outage,
        "scenarios": comparisons,
        "provenance": provenance(),
    }
    if out_path is not None:
        write_json(out_path, result)
    return result
