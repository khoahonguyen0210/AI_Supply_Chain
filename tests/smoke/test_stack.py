"""Smoke test against a running deployment (Docker Compose or kind), through the public frontend.

Signs in as the demo accounts and walks the planner workflow: question -> recommendation awaiting
approval -> approvals by the roles the policy names -> approved; then one queued optimisation job.

    SCM_SMOKE_URL=http://localhost:3000 SCM_SMOKE_PASSWORD=<demo password> \
        uv run pytest tests/smoke -m smoke

`scripts/stack.sh smoke` and `scripts/kind.sh smoke` fill both in from the generated secrets.
"""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

import httpx
import pytest

pytestmark = [
    pytest.mark.smoke,
    pytest.mark.skipif(not os.environ.get("SCM_SMOKE_URL"), reason="set SCM_SMOKE_URL"),
]

PRIMARY = "Demand for SKU-001 is expected to rise by 20%. What should I do?"
APPROVERS = {"procurement_manager": "manager", "finance": "finance"}


class Client:
    def __init__(self, user_id: str) -> None:
        self.http = httpx.Client(base_url=os.environ["SCM_SMOKE_URL"], timeout=180)
        response = self.http.post(
            "/api/auth/login",
            json={"userId": user_id, "password": os.environ.get("SCM_SMOKE_PASSWORD", "")},
        )
        assert response.status_code == 200, response.text
        self.http.headers["Authorization"] = f"Bearer {response.json()['accessToken']}"

    def get(self, path: str) -> Any:
        response = self.http.get(path)
        assert response.status_code == 200, f"{path}: {response.status_code} {response.text}"
        return response.json()

    def post(self, path: str, body: dict[str, Any], **headers: str) -> httpx.Response:
        return self.http.post(path, json=body, headers=headers)


def test_frontend_and_backend_are_up() -> None:
    base = os.environ["SCM_SMOKE_URL"]
    assert httpx.get(base, timeout=30).status_code == 200
    assert httpx.get(f"{base}/api/health", timeout=30).status_code == 200
    assert httpx.get(f"{base}/api/skus", timeout=30).status_code == 401


def test_seeded_data_is_served() -> None:
    planner = Client("planner")
    assert len(planner.get("/api/skus")) == 40
    assert planner.get("/api/documents")


def test_question_to_approved_recommendation() -> None:
    planner = Client("planner")
    created = planner.post("/api/agent/tasks", {"text": PRIMARY})
    assert created.status_code == 201, created.text
    run = created.json()
    assert run["status"] == "AWAITING_APPROVAL", run["answer"]
    assert run["citations"] and run["violations"] == []

    approval_id = run["approvalId"]
    detail = planner.get(f"/api/approvals/{approval_id}")
    for role in detail["approval"]["requiredRoles"]:
        decided = Client(APPROVERS[role]).post(
            f"/api/approvals/{approval_id}/decision",
            {"outcome": "APPROVED", "rationale": "smoke test"},
        )
        assert decided.status_code == 200, decided.text
    final = planner.get(f"/api/approvals/{approval_id}")
    assert final["approval"]["status"] == "APPROVED"
    assert final["recommendation"]["recommendation"]["status"] == "APPROVED"


def test_optimisation_runs_as_a_job() -> None:
    planner = Client("planner")
    plan = {"skuIds": ["SKU-002"], "horizonWeeks": 4, "demandMultiplier": 1.1}
    submitted = planner.post(
        "/api/jobs",
        {"type": "OPTIMIZATION", "payload": plan},
        **{"Idempotency-Key": f"smoke-{uuid.uuid4()}"},
    )
    assert submitted.status_code == 202, submitted.text
    job_id = submitted.json()["id"]
    deadline = time.time() + 180
    while time.time() < deadline:
        job = planner.get(f"/api/jobs/{job_id}")
        if job["status"] in {"SUCCEEDED", "FAILED"}:
            break
        time.sleep(1)
    assert job["status"] == "SUCCEEDED", job
    assert job["result"]["lines"] and job["result"]["violations"] == []
