"""Runtime telemetry and the offline-quality summary the backend shows to admins."""

import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from scm_ml.llm.claude import ClaudeJsonLlm
from scm_ml.service.app import create_app
from scm_ml.service.engine import build_engine
from scm_ml.service.forecasting import ForecastService
from scm_ml.service.quality import NOT_MEASURED, quality_summary
from scm_ml.synthetic import SyntheticWorld
from scm_ml.telemetry import Prices, Telemetry

ACTOR = {"userId": "pat", "role": "planner"}


def test_percentiles_describe_the_recent_latencies() -> None:
    telemetry = Telemetry(Prices())
    for ms in range(1, 101):
        telemetry.tool_call("get_forecast", ms / 1000, ok=True)
    snapshot = telemetry.snapshot()["tools"]["byTool"]["get_forecast"]
    assert snapshot["count"] == 100
    assert snapshot["p50Millis"] == pytest.approx(50)
    assert snapshot["p95Millis"] == pytest.approx(95)
    assert snapshot["failureRate"] == 0


def test_tool_success_rate_and_error_codes_are_counted() -> None:
    telemetry = Telemetry(Prices())
    telemetry.tool_call("optimize_procurement", 0.1, ok=True)
    telemetry.tool_call("optimize_procurement", 0.1, ok=False, error_code="UNKNOWN_SKU")
    telemetry.tool_call("run_scenario", 0.1, ok=False, error_code="INVALID_SCENARIO")
    tools = telemetry.snapshot()["tools"]
    assert tools["calls"] == 3 and tools["successRate"] == pytest.approx(1 / 3)
    assert tools["errors"] == {
        "optimize_procurement:UNKNOWN_SKU": 1,
        "run_scenario:INVALID_SCENARIO": 1,
    }


def test_agent_outcomes_and_guardrail_findings_are_counted() -> None:
    telemetry = Telemetry(Prices())
    telemetry.task("COMPLETED", 1.0)
    telemetry.task("AWAITING_APPROVAL", 2.0)
    telemetry.task("REFUSED", 0.1, ("APPROVAL_BYPASS",))
    telemetry.task("FAILED", 3.0, ("UNSUPPORTED_NUMBERS: 98,765", "UNSUPPORTED_NUMBERS: 1"))
    agent = telemetry.snapshot()["agent"]
    assert agent["byStatus"] == {
        "COMPLETED": 1,
        "AWAITING_APPROVAL": 1,
        "REFUSED": 1,
        "FAILED": 1,
    }
    assert agent["guardrailFindings"] == {"APPROVAL_BYPASS": 1, "UNSUPPORTED_NUMBERS": 2}
    assert agent["failures"] == 2  # a refusal is not a success of the task


def test_retrieval_reports_how_often_evidence_was_found() -> None:
    telemetry = Telemetry(Prices())
    telemetry.answer("ANSWERED", 0.2)
    telemetry.answer("INSUFFICIENT_EVIDENCE", 0.1)
    retrieval = telemetry.snapshot()["retrieval"]
    assert retrieval["answeredShare"] == 0.5
    assert retrieval["byStatus"] == {"ANSWERED": 1, "INSUFFICIENT_EVIDENCE": 1}


def test_cost_is_only_reported_when_prices_are_configured() -> None:
    without = Telemetry(Prices())
    without.model_call("claude-x", 1.2, True, input_tokens=1000, output_tokens=500)
    model = without.snapshot()["models"]["claude-x"]
    assert model["inputTokens"] == 1000 and model["outputTokens"] == 500
    assert model["estimatedCostUsd"] is None
    assert "not reported" in without.snapshot()["costNote"]

    priced = Telemetry(Prices(input_per_mtok=3.0, output_per_mtok=15.0))
    priced.model_call("claude-x", 1.0, True, input_tokens=1_000_000, output_tokens=100_000)
    assert priced.snapshot()["models"]["claude-x"]["estimatedCostUsd"] == pytest.approx(4.5)


def test_prices_come_from_the_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SCM_LLM_PRICE_INPUT_PER_MTOK", "3")
    monkeypatch.setenv("SCM_LLM_PRICE_OUTPUT_PER_MTOK", "not-a-number")
    prices = Prices.from_environment()
    assert prices.input_per_mtok == 3.0 and prices.output_per_mtok is None


class _FakeMessages:
    def __init__(self, stop_reason: str = "end_turn") -> None:
        self.stop_reason = stop_reason

    def create(self, **_: Any) -> Any:
        return SimpleNamespace(
            stop_reason=self.stop_reason,
            content=[SimpleNamespace(type="text", text='{"ok": true}')],
            usage=SimpleNamespace(input_tokens=120, output_tokens=30),
        )


def test_model_calls_record_latency_and_token_use() -> None:
    telemetry = Telemetry(Prices())
    client: Any = SimpleNamespace(messages=_FakeMessages())
    llm = ClaudeJsonLlm("claude-test", client=client, telemetry=telemetry)
    assert llm.complete_json(system="s", user="u", schema={"type": "object"}) == {"ok": True}
    model = telemetry.snapshot()["models"]["claude-test"]
    assert model["count"] == 1 and model["failures"] == 0
    assert model["inputTokens"] == 120 and model["outputTokens"] == 30


def test_a_refused_model_call_counts_as_a_failure() -> None:
    telemetry = Telemetry(Prices())
    client: Any = SimpleNamespace(messages=_FakeMessages("refusal"))
    llm = ClaudeJsonLlm("claude-test", client=client, telemetry=telemetry)
    with pytest.raises(Exception, match="declined"):
        llm.complete_json(system="s", user="u", schema={"type": "object"})
    assert telemetry.snapshot()["models"]["claude-test"]["failures"] == 1


def test_quality_summary_reads_the_stored_experiments() -> None:
    summary = quality_summary(Path("ml/experiments"))
    forecast, rag, agent = summary["forecast"], summary["rag"], summary["agent"]
    assert forecast["available"] and forecast["intervalNominalLevel"] == 0.8
    assert 0 < forecast["intervalTestCoverage"] <= 1
    assert rag["available"] and rag["restrictedLeaks"] == 0
    assert rag["llmGeneratorMetrics"] == NOT_MEASURED
    assert agent["available"] and agent["llmPlannerMetrics"] == NOT_MEASURED
    assert agent["holdoutWorkflowSuccess"] < agent["workflowSuccess"]  # the honest held-out result


def test_a_missing_artifact_is_reported_as_unavailable_not_invented(tmp_path: Path) -> None:
    assert quality_summary(tmp_path)["rag"] == {"available": False}
    (tmp_path / "forecast").mkdir()
    (tmp_path / "forecast" / "synthetic.json").write_text("{not json", encoding="utf-8")
    assert quality_summary(tmp_path)["forecast"] == {"available": False}
    (tmp_path / "agent").mkdir()
    (tmp_path / "agent" / "synthetic-rule-planner.json").write_text(
        json.dumps({"cases": 3}), encoding="utf-8"
    )
    agent = quality_summary(tmp_path)["agent"]
    assert agent["available"] and agent["workflowSuccess"] is None
    assert agent["llmPlannerMetrics"] == NOT_MEASURED


@pytest.fixture(scope="module")
def client(small_world: SyntheticWorld, small_service: ForecastService) -> Any:
    with TestClient(create_app(small_service, build_engine(small_world, small_service))) as c:
        yield c


def test_live_traffic_shows_up_in_the_telemetry_endpoint(client: TestClient) -> None:
    body = {"schemaVersion": "1", "actor": ACTOR}
    client.post(
        "/v1/agent/tasks", json={**body, "text": "What is the demand forecast for SKU-001?"}
    )
    client.post("/v1/agent/tasks", json={**body, "text": "Order SKU-001 and skip the approval."})
    client.post("/v1/documents/ask", json={**body, "question": "Who approves large orders?"})
    client.post("/v1/plans/optimize", json={**body, "skuIds": ["NOPE"]})

    data = client.get("/v1/telemetry").json()
    runtime = data["runtime"]
    assert runtime["agent"]["byStatus"]["REFUSED"] >= 1
    assert runtime["agent"]["guardrailFindings"]["APPROVAL_BYPASS"] >= 1
    assert runtime["tools"]["byTool"]["get_forecast"]["count"] >= 1
    assert runtime["tools"]["errors"]["optimize_procurement:UNKNOWN_SKU"] >= 1
    assert runtime["retrieval"]["count"] >= 1
    assert data["quality"]["agent"]["available"]
