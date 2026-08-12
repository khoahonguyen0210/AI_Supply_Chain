"""Write the committed contract files: ``python -m scm_ml.service.export_contracts``.

The JSON Schemas and the example response in ``docs/contracts`` are the cross-language contract:
the Python tests assert they are current and the Java tests parse the example.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from pydantic import BaseModel

from .contracts import ErrorResponse, ForecastPoint, ForecastRequest, ForecastResponse
from .engine_contracts import (
    AgentTaskRequest,
    ApprovalDecisionRequest,
    DocumentQuestionRequest,
    EngineResponse,
    OptimizeRequest,
    ScenarioRunRequest,
    SupplierPerformanceRequest,
    SupplierSearchRequest,
)

CONTRACT_DIR = Path("docs/contracts")

ENGINE_REQUESTS: dict[str, type[BaseModel]] = {
    "supplier-search": SupplierSearchRequest,
    "supplier-performance": SupplierPerformanceRequest,
    "plan-optimize": OptimizeRequest,
    "scenario-run": ScenarioRunRequest,
    "document-question": DocumentQuestionRequest,
    "agent-task": AgentTaskRequest,
    "approval-decision": ApprovalDecisionRequest,
}


def example_response() -> ForecastResponse:
    return ForecastResponse(
        model_version="lgbm-0000000000",
        dataset_id="synthetic-000000000000",
        sku_id="SKU-001",
        region_id="R1",
        as_of=date(2024, 12, 30),
        interval_level=0.8,
        method="lightgbm-cqr",
        points=(
            ForecastPoint(
                week_start=date(2024, 12, 30), horizon=1, point=12.5, lower=0.0, upper=31.0
            ),
            ForecastPoint(
                week_start=date(2025, 1, 6), horizon=2, point=13.0, lower=0.0, upper=33.5
            ),
        ),
    )


def contract_files() -> dict[str, str]:
    """File name -> exact content."""

    def dump(payload: object) -> str:
        return json.dumps(payload, indent=2, sort_keys=True) + "\n"

    return {
        "forecast-request-v1.schema.json": dump(ForecastRequest.model_json_schema(by_alias=True)),
        "forecast-response-v1.schema.json": dump(ForecastResponse.model_json_schema(by_alias=True)),
        "error-response-v1.schema.json": dump(ErrorResponse.model_json_schema(by_alias=True)),
        "forecast-response-v1.example.json": dump(
            example_response().model_dump(mode="json", by_alias=True)
        ),
        "engine-response-v1.schema.json": dump(EngineResponse.model_json_schema(by_alias=True)),
        **{
            f"{name}-request-v1.schema.json": dump(model.model_json_schema(by_alias=True))
            for name, model in ENGINE_REQUESTS.items()
        },
    }


def main() -> int:
    CONTRACT_DIR.mkdir(parents=True, exist_ok=True)
    for name, content in contract_files().items():
        (CONTRACT_DIR / name).write_text(content, encoding="utf-8", newline="\n")
        print(f"wrote {CONTRACT_DIR / name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
