"""Compose final answers from tool results only.

Every number below is read from an observation, so the numerical-grounding guardrail passes by
construction for the rule-based planner; it exists to catch a model that writes its own numbers.
"""

from __future__ import annotations

import re
from typing import Any

from .models import TraceStep


class Observations:
    """Read access to what the tools returned during one task."""

    def __init__(self, steps: list[TraceStep]) -> None:
        self.steps = steps

    def ok(self, tool: str) -> dict[str, Any] | None:
        for step in reversed(self.steps):
            if step.tool == tool and step.ok:
                return step.result
        return None

    def all_ok(self, tool: str) -> list[dict[str, Any]]:
        return [s.result for s in self.steps if s.tool == tool and s.ok]

    def failed(self, tool: str) -> TraceStep | None:
        for step in reversed(self.steps):
            if step.tool == tool and not step.ok:
                return step
        return None

    def any_failure_code(self, code: str) -> TraceStep | None:
        return next((s for s in reversed(self.steps) if not s.ok and s.error_code == code), None)


def n(value: float, digits: int = 0) -> str:
    return f"{value:,.{digits}f}"


def pct(rate: float) -> str:
    return f"{rate * 100:.1f}%"


def _cite(obs: dict[str, Any]) -> str:
    docs = [f"{c['document_id']} version {c['version']}" for c in obs.get("citations", [])]
    return f" [{', '.join(docs)}]" if docs else ""


_MARKER = re.compile(r"\s*\[S\d+\]")


def policy_answer(obs: dict[str, Any]) -> str:
    answer = _MARKER.sub("", obs["answer"])
    return f'Policy check "{obs["question"]}": {answer}{_cite(obs)}'


def forecast_text(obs: Observations) -> str:
    f = obs.ok("get_forecast")
    assert f is not None
    regions = "; ".join(
        f"{r['region_id']} {n(r['units'], 1)} units (80% range {n(r['interval_low'], 1)} to "
        f"{n(r['interval_high'], 1)})"
        for r in f["regions"]
    )
    return (
        f"Forecast demand for {f['sku_id']} over the next {f['horizon_weeks']} weeks is "
        f"{n(f['total_units'], 1)} units ({f['model_version']}). By region: {regions}."
    )


def inventory_text(obs: Observations) -> str:
    a = obs.ok("assess_inventory_need")
    inv = obs.ok("get_inventory")
    assert a is not None
    parts = []
    if inv is not None:
        parts.append(
            f"On hand {n(inv['total_on_hand'])} units, incoming {n(inv['total_incoming'])}, "
            f"safety stock {n(inv['total_safety_stock'])}."
        )
    if a["total_net_requirement"] > 0:
        parts.append(
            f"Against forecast demand of {n(a['total_demand'], 1)} units over "
            f"{a['horizon_weeks']} weeks the net purchase requirement is "
            f"{n(a['total_net_requirement'])} units; {a['neediest_warehouse']} is the neediest "
            f"warehouse."
        )
    else:
        parts.append(
            f"Stock on hand and incoming covers forecast demand of {n(a['total_demand'], 1)} "
            f"units plus safety stock over {a['horizon_weeks']} weeks "
            f"(net requirement {n(a['total_net_requirement'])} units), so no purchase is needed."
        )
    return " ".join(parts)


def suppliers_text(obs: Observations) -> str:
    s = obs.ok("search_suppliers")
    assert s is not None
    if not s["ranked"]:
        reasons = "; ".join(f"{k}: {', '.join(v)}" for k, v in sorted(s["rejected"].items()))
        return (
            f"No supplier is eligible for {n(s['quantity'])} units of {s['sku_id']} at "
            f"{s['warehouse_id']} within {s['max_lead_time_days']} days. Rejections: {reasons}."
        )
    top = s["ranked"][0]
    text = (
        f"{s['eligible_count']} suppliers are eligible. Top ranked is {top['supplier_id']} at "
        f"{n(top['landed_unit_cost'], 3)} per landed unit, {n(top['cost_vs_cheapest_pct'], 1)}% "
        f"above the cheapest eligible offer, lead time {top['lead_time_days']} days, reliability "
        f"{n(top['reliability'], 3)}."
    )
    cheapest = s["cheapest_overall"]
    if cheapest and not cheapest["eligible"]:
        text += (
            f" The cheapest supplier overall, {cheapest['supplier_id']} at "
            f"{n(cheapest['landed_unit_cost'], 3)}, is not eligible "
            f"({', '.join(cheapest['rejection_reasons'])}), so it is not an option."
        )
    return text


def plan_text(obs: Observations) -> str:
    p = obs.ok("optimize_procurement")
    assert p is not None
    suppliers = ", ".join(f"{b['supplier_id']} {n(b['units'])} units" for b in p["by_supplier"])
    text = (
        f"Optimized plan {p['plan_id']} ({p['solver_status']}): buy {n(p['units_ordered'])} units "
        f"in {p['orders']} orders ({suppliers}), order value {n(p['order_value'])}, total cost "
        f"{n(p['objective'])}, fill rate {pct(p['fill_rate'])}."
    )
    if p["violations"]:
        kinds = ", ".join(sorted({v["kind"] for v in p["violations"]}))
        text += f" It violates constraints ({kinds}), so it is not recommended as is."
    else:
        text += " It satisfies every constraint."
    if p["binding_constraints"]:
        top = p["binding_constraints"][0]
        text += (
            f" Tightest constraint: {top['kind']} {top['subject']} at {pct(top['utilization'])}."
        )
    return text


def scenario_text(result: dict[str, Any]) -> str:
    params = ", ".join(f"{k}={v}" for k, v in result["parameters"].items())
    base = (
        f"{result['scenario_type']} ({params})"
        f": holding the plan costs {n(result['disrupted_objective_delta'])} more; re-optimizing "
        f"costs {n(result['response_objective_delta'])} more (resilience cost "
        f"{n(result['resilience_cost'])}) and saves {n(result['response_benefit'])} versus holding "
        f"the plan; customer fill rate after response {pct(result['response_customer_fill_rate'])}."
    )
    shifts = result["supplier_shifts"]
    if shifts:
        moved = ", ".join(
            f"{s['supplier_id']} {n(s['baseline_units'])} to {n(s['response_units'])} units"
            for s in shifts
        )
        base += f" Supplier shifts: {moved}."
    return base


def performance_text(obs: Observations) -> str:
    s = obs.ok("get_supplier_performance")
    assert s is not None
    contracts = "; ".join(
        f"{c['contract_id']} {c['status']}"
        f"{'' if c['in_force'] else ' (not in force)'} until {c['effective_to']}, payment "
        f"{c['payment_terms_days']} days"
        for c in s["contracts"]
    )
    on_time = pct(s["on_time_rate"]) if s["on_time_rate"] is not None else "n/a"
    return (
        f"{s['supplier_id']} ({s['name']}): reliability {n(s['reliability'], 3)}, quality "
        f"{n(s['quality_score'], 3)}, {s['delivered_orders']} delivered orders with on-time "
        f"rate {on_time}. Contracts: {contracts or 'none'}."
    )


def approval_text(obs: Observations) -> str:
    po = obs.ok("prepare_purchase_order")
    if po is None:
        denied = obs.any_failure_code("NOT_AUTHORIZED")
        if denied is not None:
            return (
                "Your role cannot prepare purchase orders, so this stays a recommendation; ask a "
                "planner or procurement manager to prepare the order."
            )
        return ""
    return (
        f"Recommendation {po['recommendation_id']} is pending approval ({po['approval_id']}) from "
        f"{', '.join(po['required_approver_roles'])}; order value {n(po['order_value'])}. "
        f"Nothing is ordered until it is approved."
    )
