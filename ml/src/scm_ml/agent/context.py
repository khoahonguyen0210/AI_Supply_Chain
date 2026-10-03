from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace

from scm_ml.knowledge import (
    EMBEDDING_DIM,
    AnswerGenerator,
    Embedder,
    ExtractiveGenerator,
    GroundedAnswerer,
    HashingEmbedder,
    KnowledgeStore,
    Retriever,
    build_corpus,
    ingest,
)
from scm_ml.optimization import ProcurementParams
from scm_ml.scenario.execution import DecisionResult
from scm_ml.scenario.inputs import PlanningInputs
from scm_ml.service.contracts import ForecastPoint, ForecastRequest
from scm_ml.service.forecasting import ForecastService
from scm_ml.sourcing import SourcingCatalog
from scm_ml.synthetic import SyntheticWorld

from .intents import IntentMatcher
from .models import ToolError


@dataclass(frozen=True)
class PlanRecord:
    plan_id: str
    owner: str
    sku_ids: tuple[str, ...]
    horizon_weeks: int
    demand_multiplier: float
    inputs: PlanningInputs
    result: DecisionResult


class PlanningContext:
    def __init__(
        self,
        world: SyntheticWorld,
        service: ForecastService,
        answerer: GroundedAnswerer,
        plan_namespace: str = "",
    ) -> None:
        """`plan_namespace` keeps plan and recommendation ids unique across restarts."""
        self.world, self.service, self.answerer = world, service, answerer
        self._plan_namespace = plan_namespace
        self.as_of = world.as_of
        self.catalog = SourcingCatalog.from_world(world)
        self._plans: dict[str, PlanRecord] = {}
        self._intents: IntentMatcher | None = None

    def intents(self) -> IntentMatcher:
        if self._intents is None:
            names = tuple(s.name for s in self.catalog.suppliers.values())
            self._intents = IntentMatcher(self.answerer.retriever.embedder, names)
        return self._intents

    def require_sku(self, sku_id: str) -> None:
        if sku_id not in self.catalog.skus:
            raise ToolError("UNKNOWN_SKU", f"unknown SKU {sku_id}")

    def require_supplier(self, supplier_id: str) -> None:
        if supplier_id not in self.catalog.suppliers:
            raise ToolError("UNKNOWN_SUPPLIER", f"unknown supplier {supplier_id}")

    def require_warehouse(self, warehouse_id: str) -> None:
        if warehouse_id not in self.catalog.warehouses:
            raise ToolError("UNKNOWN_WAREHOUSE", f"unknown warehouse {warehouse_id}")

    def regions_with_demand(self, sku_id: str) -> list[str]:
        return sorted(region for sku, region in self.service.history.series if sku == sku_id)

    def forecast(
        self, sku_id: str, region_id: str, horizon_weeks: int
    ) -> tuple[ForecastPoint, ...]:
        response = self.service.forecast(
            ForecastRequest(
                sku_id=sku_id, region_id=region_id, as_of=self.as_of, horizon_weeks=horizon_weeks
            )
        )
        return response.points

    def regional_demand(
        self, sku_ids: tuple[str, ...], horizon_weeks: int, multiplier: float
    ) -> dict[tuple[str, str], float]:
        demand: dict[tuple[str, str], float] = {}
        for sku_id in sku_ids:
            regions = self.regions_with_demand(sku_id)
            if not regions:
                raise ToolError("NO_DEMAND_HISTORY", f"no demand history for {sku_id}")
            for region_id in regions:
                points = self.forecast(sku_id, region_id, horizon_weeks)
                demand[(sku_id, region_id)] = multiplier * sum(p.point for p in points)
        return demand

    def scoped_inputs(
        self,
        sku_ids: tuple[str, ...],
        *,
        horizon_weeks: int,
        multiplier: float,
        params: ProcurementParams,
    ) -> PlanningInputs:
        chosen = set(sku_ids)
        catalog = replace(
            self.catalog,
            skus={k: v for k, v in self.catalog.skus.items() if k in chosen},
            offers=tuple(o for o in self.catalog.offers if o.sku_id in chosen),
        )
        return PlanningInputs(
            as_of=self.as_of,
            catalog=catalog,
            inventory=tuple(p for p in self.world.inventory if p.sku_id in chosen),
            lanes=tuple(self.world.lanes),
            regional_demand=self.regional_demand(sku_ids, horizon_weeks, multiplier),
            params=params,
        )

    def store_plan(
        self,
        *,
        owner: str,
        sku_ids: tuple[str, ...],
        horizon_weeks: int,
        demand_multiplier: float,
        inputs: PlanningInputs,
        result: DecisionResult,
    ) -> PlanRecord:
        plan_id = f"PLAN-{self._plan_namespace}{len(self._plans) + 1:03d}"
        record = PlanRecord(
            plan_id=plan_id,
            owner=owner,
            sku_ids=sku_ids,
            horizon_weeks=horizon_weeks,
            demand_multiplier=demand_multiplier,
            inputs=inputs,
            result=result,
        )
        self._plans[plan_id] = record
        return record

    def plan(self, plan_id: str, owner: str) -> PlanRecord:
        record = self._plans.get(plan_id)
        if record is None or record.owner != owner:
            raise ToolError("UNKNOWN_PLAN", f"no plan {plan_id} for this user")
        return record

    def delivery_history(self) -> dict[str, tuple[int, int, int]]:
        stats: dict[str, list[int]] = defaultdict(lambda: [0, 0, 0])
        for po in self.world.purchase_orders:
            if po.delivered_at is None:
                continue
            row = stats[po.supplier_id]
            row[0] += 1
            row[1] += po.delivered_at <= po.expected_delivery
            row[2] += (po.delivered_quantity or 0) >= po.quantity
        return {k: (v[0], v[1], v[2]) for k, v in stats.items()}


def build_planning_context(
    world: SyntheticWorld,
    service: ForecastService,
    *,
    embedder: Embedder | None = None,
    generator: AnswerGenerator | None = None,
    plan_namespace: str = "",
    knowledge: KnowledgeStore | None = None,
) -> PlanningContext:
    embedder = embedder or HashingEmbedder()
    store = knowledge
    if store is None:
        store = KnowledgeStore(EMBEDDING_DIM)
        ingest(build_corpus(world).documents, embedder, store)
    answerer = GroundedAnswerer(Retriever(store, embedder), generator or ExtractiveGenerator())
    return PlanningContext(world, service, answerer, plan_namespace)
