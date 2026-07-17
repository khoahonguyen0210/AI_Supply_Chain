from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Sequence

from pydantic import Field, computed_field

from scm_common.domain import DomainModel, PurchaseLine, ScenarioType
from scm_ml.optimization.binding import (
    BindingConstraint,
    BindingKind,
    allocation_binding,
    procurement_binding,
)

from .execution import DecisionResult, ScenarioRun
from .inputs import AssumptionChange

TOP_CHANGES = 15


class OutcomeSummary(DomainModel):
    objective: float
    spend: float
    fill_rate: float = Field(description="Warehouse-level fill rate of the procurement plan.")
    unmet_demand: float
    orders: int
    units_ordered: int
    violations_by_kind: dict[str, int]
    customer_fill_rate: float = Field(description="Fill rate of regional demand after allocation.")
    customer_unmet_units: int
    shipping_cost: float
    mean_transit_days: float


class Delta(DomainModel):
    absolute: float
    percent: float | None = Field(description="Relative to the baseline; None if baseline is 0.")


class BindingChange(DomainModel):
    kind: BindingKind
    subject: str
    utilization: float


class ProcurementChange(DomainModel):
    supplier_id: str
    sku_id: str
    warehouse_id: str
    baseline_units: int
    response_units: int

    @computed_field  # type: ignore[prop-decorator]
    @property
    def delta(self) -> int:
        return self.response_units - self.baseline_units


class SupplierShift(DomainModel):
    supplier_id: str
    baseline_units: int
    response_units: int


class ChangedAllocations(DomainModel):
    changed_purchase_lines: int
    units_reallocated: int = Field(
        description="Sum of absolute unit changes across purchase lines."
    )
    largest_changes: tuple[ProcurementChange, ...]
    supplier_shifts: tuple[SupplierShift, ...]
    changed_shipment_routes: int
    shipment_units_moved: int = Field(description="Sum of absolute unit changes across routes.")


class ScenarioComparison(DomainModel):
    scenario_id: str
    name: str
    scenario_type: ScenarioType
    changes: tuple[AssumptionChange, ...]
    baseline: OutcomeSummary
    disrupted: OutcomeSummary
    response: OutcomeSummary
    objective_delta_disrupted: Delta
    objective_delta_response: Delta
    service_level_delta_disrupted: float = Field(description="Customer fill rate vs baseline.")
    service_level_delta_response: float
    resilience_cost: float = Field(
        description="Extra objective cost of the best response relative to the baseline plan."
    )
    response_benefit: float = Field(
        description="Objective saved by re-optimizing instead of holding the baseline plan."
    )
    commitment_violations: dict[str, int]
    baseline_binding: dict[str, int]
    response_binding: dict[str, int]
    newly_binding: tuple[BindingChange, ...]
    no_longer_binding: tuple[BindingChange, ...]
    changed_allocations: ChangedAllocations


def _summary(result: DecisionResult) -> OutcomeSummary:
    p, a = result.procurement.metrics, result.allocation.metrics
    return OutcomeSummary(
        objective=p.objective,
        spend=p.spend,
        fill_rate=p.fill_rate,
        unmet_demand=p.unmet_demand,
        orders=p.orders,
        units_ordered=p.units_ordered,
        violations_by_kind=dict(Counter(v.kind.value for v in p.violations)),
        customer_fill_rate=a.fill_rate,
        customer_unmet_units=a.unmet_units,
        shipping_cost=a.shipping_cost,
        mean_transit_days=a.mean_transit_days,
    )


def _delta(value: float, baseline: float) -> Delta:
    return Delta(
        absolute=value - baseline,
        percent=None if baseline == 0 else 100.0 * (value - baseline) / baseline,
    )


def _binding(result: DecisionResult) -> list[BindingConstraint]:
    return procurement_binding(result.problem, result.procurement.lines) + allocation_binding(
        result.allocation_problem, result.allocation.shipments
    )


def _changes(items: Sequence[BindingConstraint]) -> tuple[BindingChange, ...]:
    return tuple(
        BindingChange(kind=c.kind, subject=c.subject, utilization=c.utilization)
        for c in sorted(items, key=lambda c: (c.kind.value, c.subject))
    )


def _units(lines: Sequence[PurchaseLine]) -> dict[tuple[str, str, str], int]:
    units: dict[tuple[str, str, str], int] = defaultdict(int)
    for line in lines:
        units[(line.supplier_id, line.sku_id, line.warehouse_id)] += line.quantity
    return units


def _changed_allocations(baseline: DecisionResult, response: DecisionResult) -> ChangedAllocations:
    before, after = _units(baseline.procurement.lines), _units(response.procurement.lines)
    changes = [
        ProcurementChange(
            supplier_id=key[0],
            sku_id=key[1],
            warehouse_id=key[2],
            baseline_units=before.get(key, 0),
            response_units=after.get(key, 0),
        )
        for key in sorted(set(before) | set(after))
        if before.get(key, 0) != after.get(key, 0)
    ]
    shifts = []
    for supplier_id in sorted({k[0] for k in before} | {k[0] for k in after}):
        b = sum(v for k, v in before.items() if k[0] == supplier_id)
        r = sum(v for k, v in after.items() if k[0] == supplier_id)
        if b != r:
            shifts.append(
                SupplierShift(supplier_id=supplier_id, baseline_units=b, response_units=r)
            )
    moved: dict[tuple[str, str, str], int] = defaultdict(int)
    for shipment in baseline.allocation.shipments:
        moved[(shipment.sku_id, shipment.warehouse_id, shipment.region_id)] -= shipment.quantity
    for shipment in response.allocation.shipments:
        moved[(shipment.sku_id, shipment.warehouse_id, shipment.region_id)] += shipment.quantity
    changed_routes = {k: v for k, v in moved.items() if v != 0}
    largest = sorted(changes, key=lambda c: (-abs(c.delta), c.supplier_id, c.sku_id))[:TOP_CHANGES]
    return ChangedAllocations(
        changed_purchase_lines=len(changes),
        units_reallocated=sum(abs(c.delta) for c in changes),
        largest_changes=tuple(largest),
        supplier_shifts=tuple(shifts),
        changed_shipment_routes=len(changed_routes),
        shipment_units_moved=sum(abs(v) for v in changed_routes.values()),
    )


def compare_scenario(run: ScenarioRun) -> ScenarioComparison:
    baseline = _summary(run.baseline)
    disrupted = _summary(run.disrupted)
    response = _summary(run.response)
    before = {(c.kind, c.subject): c for c in _binding(run.baseline)}
    after = {(c.kind, c.subject): c for c in _binding(run.response)}
    return ScenarioComparison(
        scenario_id=run.scenario.scenario_id,
        name=run.scenario.name,
        scenario_type=run.scenario.scenario_type,
        changes=run.changes,
        baseline=baseline,
        disrupted=disrupted,
        response=response,
        objective_delta_disrupted=_delta(disrupted.objective, baseline.objective),
        objective_delta_response=_delta(response.objective, baseline.objective),
        service_level_delta_disrupted=disrupted.customer_fill_rate - baseline.customer_fill_rate,
        service_level_delta_response=response.customer_fill_rate - baseline.customer_fill_rate,
        resilience_cost=response.objective - baseline.objective,
        response_benefit=disrupted.objective - response.objective,
        commitment_violations=dict(Counter(v.kind.value for v in run.commitment_violations)),
        baseline_binding=dict(Counter(k[0].value for k in before)),
        response_binding=dict(Counter(k[0].value for k in after)),
        newly_binding=_changes([c for k, c in after.items() if k not in before]),
        no_longer_binding=_changes([c for k, c in before.items() if k not in after]),
        changed_allocations=_changed_allocations(run.baseline, run.response),
    )
