"""CLI: the final demo, one planner story told through the running stack's public API.

    uv run python -m scm_ml.demo --password <demo password> [--url http://localhost:3000]

Steps (docs/demo.md): a vague question, clarification, forecast, inventory need, supplier ranking,
optimised plan, a disruption scenario, policy and contract evidence, the copilot's trade-offs, human
approval, the recorded decision, and an outcome evaluated later. Everything shown is read from API
responses; the only simulated input is the later actual demand, labelled SIMULATED.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from typing import Any

import httpx

from scm_ml.feedback.actuals import SIMULATED, simulate_demand
from scm_ml.synthetic import SyntheticConfig
from scm_ml.synthetic.generator import generate_world_with_future, outcome_rng

VAGUE = "I'm worried we will run short on something next month. What should I do?"
SPECIFIC = "Demand for SKU-001 is expected to rise by 20%. What should I do?"
APPROVERS = {"procurement_manager": "manager", "finance": "finance", "admin": "admin"}


class Session:
    def __init__(self, url: str, user: str, password: str) -> None:
        self.http = httpx.Client(base_url=url, timeout=300)
        response = self.http.post("/api/auth/login", json={"userId": user, "password": password})
        response.raise_for_status()
        self.http.headers["Authorization"] = f"Bearer {response.json()['accessToken']}"
        self.user = user

    def get(self, path: str, **params: Any) -> Any:
        response = self.http.get(path, params=params)
        response.raise_for_status()
        return response.json()

    def post(self, path: str, body: Any) -> Any:
        response = self.http.post(path, json=body)
        if response.status_code >= 400:
            raise SystemExit(
                f"{self.user}: POST {path} -> {response.status_code} {response.text[:400]}"
            )
        return response.json()


def heading(n: int, title: str) -> None:
    print(f"\n{n:>2}. {title}")


def say(*lines: str) -> None:
    for line in lines:
        print(f"    {line}")


def tool_outputs(run: dict[str, Any], tool: str) -> list[dict[str, Any]]:
    return [
        step
        for step in run["trace"]
        if step.get("kind") == "TOOL_CALL" and step.get("tool") == tool
    ]


def short(value: Any, limit: int = 160) -> str:
    text = str(value)
    return text if len(text) <= limit else text[: limit - 3] + "..."


def show_tool(run: dict[str, Any], tool: str) -> None:
    calls = tool_outputs(run, tool)
    if not calls:
        say(f"(the copilot did not call {tool})")
        return
    for step in calls:
        say(f"tool {tool}({short(step.get('arguments', {}), 120)})")
        say(f"  -> {short(step.get('summary') or step.get('result') or step.get('output'), 300)}")


def lines(items: Iterable[Any], limit: int = 6) -> None:
    for i, item in enumerate(items):
        if i == limit:
            say("...")
            break
        say(f"- {short(item, 200)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the planner demo against a running stack.")
    parser.add_argument("--url", default="http://localhost:3000")
    parser.add_argument(
        "--password", required=True, help="the demo password (SCM_DEMO_PASSWORD in .env)"
    )
    args = parser.parse_args(argv)

    planner = Session(args.url, "planner", args.password)

    heading(1, "The planner asks a vague question")
    say(f'"{VAGUE}"')
    first = planner.post("/api/agent/tasks", {"text": VAGUE})
    say(f"copilot status: {first['status']}")
    say(short(first["answer"], 400))
    conversation = first.get("conversationId")

    say("", f'The planner is specific: "{SPECIFIC}"')
    run = planner.post("/api/agent/tasks", {"text": SPECIFIC, "conversationId": conversation})
    say(f"copilot status: {run['status']}")

    heading(2, "Forecast")
    show_tool(run, "get_forecast")
    heading(3, "Inventory need")
    show_tool(run, "assess_inventory_need")
    heading(4, "Suppliers filtered and ranked")
    show_tool(run, "search_suppliers")
    heading(5, "Optimised purchase plan")
    show_tool(run, "optimize_procurement")
    heading(6, "Disruption scenario")
    show_tool(run, "run_scenario")
    heading(7, "Policy and contract evidence (RAG)")
    show_tool(run, "search_policies")
    lines(
        f"[{c.get('documentId')} v{c.get('version')}] {short(c.get('excerpt', ''), 150)}"
        for c in run["citations"]
    )

    heading(8, "The copilot explains the trade-offs")
    say(*run["answer"].splitlines()[:25])
    if run.get("assumptions"):
        say("Assumptions:")
        lines(run["assumptions"])
    if run["status"] != "AWAITING_APPROVAL":
        print(
            f"\nThe copilot ended in {run['status']}, not awaiting approval; stopping.",
            file=sys.stderr,
        )
        return 1

    approval_id, recommendation_id = run["approvalId"], run["recommendationId"]
    detail = planner.get(f"/api/approvals/{approval_id}")
    heading(9, "Human approval")
    required = detail["approval"]["requiredRoles"]
    say(
        f"approval {approval_id}: status {detail['approval']['status']}, needs "
        f"{', '.join(required)}"
    )
    for line in detail["recommendation"]["lines"][:5]:
        say(f"- {short(line, 200)}")
    own = planner.http.post(f"/api/approvals/{approval_id}/decision", json={"outcome": "APPROVED"})
    say(f"the planner tries to approve their own request: HTTP {own.status_code}")
    for role in required:
        approver = Session(args.url, APPROVERS[role], args.password)
        approver.post(
            f"/api/approvals/{approval_id}/decision",
            {"outcome": "APPROVED", "rationale": "Demo: cost and service trade-off accepted"},
        )
        say(f"{approver.user} ({role}) approved")

    heading(10, "The decision is recorded")
    final = planner.get(f"/api/approvals/{approval_id}")
    say(
        f"approval {final['approval']['status']}, recommendation "
        f"{final['recommendation']['recommendation']['status']}"
    )
    lines(
        f"{d.get('decidedBy')} as {d.get('approverRole')}: {d.get('outcome')} at "
        f"{d.get('decidedAt')}"
        for d in final["decisions"]
    )

    heading(11, "Later: the outcome is recorded and evaluated")
    skus = sorted({line["skuId"] for line in final["recommendation"]["lines"]})
    world, future = generate_world_with_future(SyntheticConfig())
    actual = simulate_demand(world, future, outcome_rng(world.config), 8)
    actual = actual[actual["sku_id"].isin(skus)]
    records = [
        {
            "skuId": sku,
            "regionId": region,
            "weekStart": week.isoformat(),
            "quantity": float(quantity),
        }
        for sku, region, week, quantity in zip(
            actual["sku_id"],
            actual["region_id"],
            actual["week_start"],
            actual["quantity"],
            strict=True,
        )
    ]
    recorded = planner.post("/api/outcomes/demand", {"source": SIMULATED, "records": records})
    say(
        f"recorded {recorded['recorded']} weekly demand actuals for {', '.join(skus)} "
        f"(source {SIMULATED})"
    )
    result = planner.get("/api/outcomes/evaluation", recommendationId=recommendation_id)
    forecast = result["evaluation"]["forecast"]
    say(
        f"forecast snapshot of model {', '.join(result['forecastModelVersions']) or '(none)'}: "
        f"{forecast['points']} points scored, {forecast['awaitingActuals']} awaiting actuals"
    )
    overall = forecast["overall"] or {}
    say(
        "forecast vs actual: "
        + ", ".join(f"{k} {v:.3f}" for k, v in overall.items() if isinstance(v, float))
    )
    deliveries = result["evaluation"]["deliveries"]["overall"]
    say(
        f"supplier deliveries: {deliveries['delivered']} delivered, {deliveries['pending']} pending"
    )
    print("\nDemo complete.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
