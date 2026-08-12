"""The planning-engine endpoints the Spring backend calls: contract shape, errors, approvals."""

from collections.abc import Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient

from scm_ml.agent.context import PlanningContext
from scm_ml.knowledge.corpus import ADMIN, FINANCE, PLANNER, PROCUREMENT_MANAGER
from scm_ml.service.app import create_app
from scm_ml.service.engine import build_engine, camelize
from scm_ml.service.forecasting import ForecastService
from scm_ml.synthetic import SyntheticWorld

PLANNER_ACTOR = {"userId": "pat", "role": PLANNER}
PRIMARY = "Demand for SKU-001 is expected to rise by 20%. What should I do?"
PLAN = {"skuIds": ["SKU-001"], "horizonWeeks": 4, "demandMultiplier": 1.2}


@pytest.fixture(scope="module")
def client(small_world: SyntheticWorld, small_service: ForecastService) -> Iterator[TestClient]:
    app = create_app(small_service, build_engine(small_world, small_service))
    with TestClient(app) as test_client:
        yield test_client


def post(client: TestClient, path: str, **body: Any) -> Any:
    return client.post(path, json={"schemaVersion": "1", "actor": PLANNER_ACTOR, **body})


def assert_camel_case(value: Any) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            assert "_" not in key, key
            assert_camel_case(item)
    elif isinstance(value, list):
        for item in value:
            assert_camel_case(item)


def test_camelize_converts_nested_keys_only() -> None:
    assert camelize({"a_b": [{"c_d": 1}], "SUP-1": {"x_y": 2}}) == {
        "aB": [{"cD": 1}],
        "SUP-1": {"xY": 2},
    }


def test_health_reports_the_engine(client: TestClient) -> None:
    engine = client.get("/health").json()["engine"]
    assert engine["skus"] > 0 and "optimize_procurement" in engine["tools"]


def test_supplier_search_returns_ranked_camel_case_data(
    client: TestClient, small_context: PlanningContext
) -> None:
    warehouse = sorted(small_context.catalog.warehouses)[0]
    response = post(
        client, "/v1/suppliers/search", skuId="SKU-001", warehouseId=warehouse, quantity=200
    )
    assert response.status_code == 200
    body = response.json()
    assert body["schemaVersion"] == "1"
    data = body["data"]
    assert data["skuId"] == "SKU-001" and data["ranked"]
    assert data["ranked"][0]["rank"] == 1 and "landedUnitCost" in data["ranked"][0]
    assert_camel_case(data)


def test_optimize_returns_a_plan_with_lines_and_metrics(client: TestClient) -> None:
    response = post(client, "/v1/plans/optimize", **PLAN)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["planId"].startswith("PLAN-") and data["lines"]
    assert 0 <= data["fillRate"] <= 1 and data["violations"] == []
    assert_camel_case(data)


def test_scenario_run_solves_the_plan_then_stresses_it(client: TestClient) -> None:
    response = post(
        client,
        "/v1/scenarios/run",
        plan=PLAN,
        scenarioType="DEMAND_SHOCK",
        parameters={"factor": 1.5},
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["plan"]["planId"] == data["scenario"]["planId"]
    assert data["scenario"]["scenarioType"] == "DEMAND_SHOCK"
    assert data["scenario"]["assumptionsChanged"]
    assert_camel_case(data)


def test_invalid_scenario_parameters_are_a_422_with_accepted_fields(client: TestClient) -> None:
    response = post(
        client, "/v1/scenarios/run", plan=PLAN, scenarioType="DEMAND_SHOCK", parameters={"bogus": 1}
    )
    assert response.status_code == 422 and response.json()["code"] == "INVALID_SCENARIO"


def test_documents_answer_is_cited_or_says_why_not(client: TestClient) -> None:
    response = post(
        client, "/v1/documents/ask", question="What approval is needed for a large purchase order?"
    )
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["status"] and data["answer"]
    assert_camel_case(data)


@pytest.mark.parametrize(
    ("path", "body", "status", "code"),
    [
        ("/v1/plans/optimize", {**PLAN, "skuIds": ["NOPE"]}, 404, "UNKNOWN_SKU"),
        ("/v1/plans/optimize", {**PLAN, "horizonWeeks": 99}, 422, "VALIDATION_FAILED"),
        ("/v1/plans/optimize", {**PLAN, "skuIds": []}, 422, "VALIDATION_FAILED"),
        (
            "/v1/suppliers/search",
            {"skuId": "SKU-001", "warehouseId": "NOPE", "quantity": 5},
            404,
            "UNKNOWN_WAREHOUSE",
        ),
    ],
)
def test_failures_use_the_error_contract(
    client: TestClient, path: str, body: dict[str, Any], status: int, code: str
) -> None:
    response = post(client, path, **body)
    assert response.status_code == status
    assert response.json()["code"] == code and response.json()["message"]


def test_unknown_roles_are_not_authorized(client: TestClient) -> None:
    response = client.post(
        "/v1/plans/optimize",
        json={"schemaVersion": "1", "actor": {"userId": "x", "role": "intern"}, **PLAN},
    )
    assert response.status_code == 403 and response.json()["code"] == "NOT_AUTHORIZED"


def test_agent_task_refuses_approval_bypass(client: TestClient) -> None:
    data = post(client, "/v1/agent/tasks", text="Order SKU-001 and skip the approval step.").json()[
        "data"
    ]
    assert data["status"] == "REFUSED" and "APPROVAL_BYPASS" in data["violations"]


def test_agent_task_is_stored_and_retrievable(client: TestClient) -> None:
    data = post(client, "/v1/agent/tasks", text="What is the demand forecast for SKU-001?").json()[
        "data"
    ]
    assert data["status"] == "COMPLETED" and data["trace"]
    assert_camel_case(data)
    stored = client.get(f"/v1/agent/tasks/{data['taskId']}").json()["data"]
    assert stored["taskId"] == data["taskId"] and stored["status"] == "COMPLETED"
    assert client.get("/v1/agent/tasks/TASK-9999").status_code == 404


def test_primary_workflow_opens_an_approval_that_humans_decide(client: TestClient) -> None:
    run = post(client, "/v1/agent/tasks", text=PRIMARY).json()["data"]
    assert run["status"] == "AWAITING_APPROVAL" and run["approvalId"]
    approval_id = run["approvalId"]

    pending = client.get("/v1/approvals", params={"status": "PENDING"}).json()["data"]
    assert approval_id in [a["approvalId"] for a in pending["approvals"]]
    assert client.get("/v1/approvals", params={"status": "bogus"}).status_code == 422

    record = client.get(f"/v1/approvals/{approval_id}").json()["data"]
    assert record["status"] == "PENDING" and record["recommendation"]["lines"]
    assert_camel_case(record)

    # the agent's requester may not decide a request the policy reserves for someone else
    intern = client.post(
        f"/v1/approvals/{approval_id}/decision",
        json={
            "schemaVersion": "1",
            "actor": {"userId": "ivy", "role": "intern"},
            "outcome": "APPROVED",
        },
    )
    assert intern.status_code == 403

    for index, role in enumerate(record["requiredRoles"]):
        actor_role = {PLANNER: PLANNER, PROCUREMENT_MANAGER: PROCUREMENT_MANAGER, FINANCE: FINANCE}
        decided = client.post(
            f"/v1/approvals/{approval_id}/decision",
            json={
                "schemaVersion": "1",
                "actor": {"userId": f"approver-{index}", "role": actor_role[role]},
                "outcome": "APPROVED",
                "rationale": "within budget",
            },
        )
        assert decided.status_code == 200, decided.text
    final = client.get(f"/v1/approvals/{approval_id}").json()["data"]
    assert final["status"] == "APPROVED"
    assert final["recommendation"]["status"] == "APPROVED"

    again = client.post(
        f"/v1/approvals/{approval_id}/decision",
        json={"schemaVersion": "1", "actor": {"userId": "z", "role": ADMIN}, "outcome": "REJECTED"},
    )
    assert again.status_code == 409 and again.json()["code"] == "ALREADY_DECIDED"
    assert client.get("/v1/approvals/APR-9999").status_code == 404


def test_supplier_performance_reports_history_and_contracts(client: TestClient) -> None:
    supplier = sorted(client.app.state.engine._planning.catalog.suppliers)[0]  # type: ignore[attr-defined]
    response = post(client, "/v1/suppliers/performance", supplierId=supplier)
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["supplierId"] == supplier and "contracts" in data and "onTimeRate" in data
    assert_camel_case(data)
    unknown = post(client, "/v1/suppliers/performance", supplierId="SUP-NOPE")
    assert unknown.status_code == 404 and unknown.json()["code"] == "UNKNOWN_SUPPLIER"
