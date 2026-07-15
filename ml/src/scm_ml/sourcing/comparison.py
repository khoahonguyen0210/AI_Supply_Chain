from __future__ import annotations

from collections import Counter

from pydantic import Field

from scm_common.domain import DomainModel

from .catalog import SourcingCatalog, SourcingRequest
from .eligibility import EligibilityDecision, RejectionReason, evaluate_eligibility
from .ranking import Criterion, RankedOffer, RankingWeights, rank_offers


class ComparisonRow(DomainModel):
    rank: int
    supplier_id: str
    supplier_name: str
    offer_id: str
    score: float
    unit_price: float
    shipping_cost_per_unit: float
    landed_unit_cost: float
    total_cost: float = Field(description="Landed unit cost x requested quantity.")
    cost_vs_cheapest_pct: float = Field(ge=0)
    lead_time_days: int
    lead_time_vs_fastest_days: int = Field(ge=0)
    reliability: float
    quality_score: float
    capacity_headroom: float = Field(description="Available capacity / requested quantity.")
    contract_fit: float


class CriterionLeader(DomainModel):
    criterion: Criterion
    supplier_id: str


class SupplierComparison(DomainModel):
    request: SourcingRequest
    rows: tuple[ComparisonRow, ...]
    leaders: tuple[CriterionLeader, ...]
    trade_offs: tuple[str, ...] = Field(
        description="Plain-language statements of what the top-ranked supplier gives up or gains."
    )


class SourcingResult(DomainModel):
    request: SourcingRequest
    weights: RankingWeights
    decisions: tuple[EligibilityDecision, ...]
    rejection_counts: dict[str, int]
    ranking: tuple[RankedOffer, ...]
    comparison: SupplierComparison


def _component(ranked: RankedOffer, criterion: Criterion) -> float:
    return next(c.raw_value for c in ranked.components if c.criterion == criterion)


def _leader(rows: list[ComparisonRow], criterion: Criterion) -> str:
    key = {
        Criterion.COST: lambda r: (r.landed_unit_cost, r.supplier_id),
        Criterion.LEAD_TIME: lambda r: (r.lead_time_days, r.supplier_id),
        Criterion.RELIABILITY: lambda r: (-r.reliability, r.supplier_id),
        Criterion.CAPACITY: lambda r: (-r.capacity_headroom, r.supplier_id),
        Criterion.QUALITY: lambda r: (-r.quality_score, r.supplier_id),
        Criterion.CONTRACT_FIT: lambda r: (-r.contract_fit, r.supplier_id),
    }[criterion]
    return min(rows, key=key).supplier_id


def _trade_offs(rows: list[ComparisonRow]) -> tuple[str, ...]:
    if not rows:
        return ()
    top = rows[0]
    cheapest = min(rows, key=lambda r: (r.landed_unit_cost, r.supplier_id))
    fastest = min(rows, key=lambda r: (r.lead_time_days, r.supplier_id))
    most_reliable = max(rows, key=lambda r: (r.reliability, r.supplier_id))
    statements: list[str] = []
    if top.supplier_id == cheapest.supplier_id:
        statements.append(f"{top.supplier_id} is both top-ranked and the cheapest option.")
    else:
        statements.append(
            f"{top.supplier_id} costs {top.cost_vs_cheapest_pct:.1f}% more than the cheapest "
            f"option ({cheapest.supplier_id}) per landed unit."
        )
    if top.supplier_id != fastest.supplier_id:
        statements.append(
            f"{top.supplier_id} delivers {top.lead_time_vs_fastest_days} days slower than the "
            f"fastest option ({fastest.supplier_id})."
        )
    if top.supplier_id != most_reliable.supplier_id:
        statements.append(
            f"{most_reliable.supplier_id} is more reliable ({most_reliable.reliability:.3f} vs "
            f"{top.reliability:.3f}) but ranks #{most_reliable.rank}."
        )
    return tuple(statements)


def build_comparison(
    request: SourcingRequest, ranking: list[RankedOffer], catalog: SourcingCatalog
) -> SupplierComparison:
    offers = {o.offer_id: o for o in catalog.offers_for_sku(request.sku_id)}
    if not ranking:
        return SupplierComparison(request=request, rows=(), leaders=(), trade_offs=())
    cheapest = min(r.landed_unit_cost for r in ranking)
    fastest = min(offers[r.offer_id].lead_time_days for r in ranking)
    rows: list[ComparisonRow] = []
    for ranked in ranking:
        offer = offers[ranked.offer_id]
        supplier = catalog.suppliers[ranked.supplier_id]
        rows.append(
            ComparisonRow(
                rank=ranked.rank,
                supplier_id=ranked.supplier_id,
                supplier_name=supplier.name,
                offer_id=ranked.offer_id,
                score=ranked.score,
                unit_price=offer.unit_price,
                shipping_cost_per_unit=offer.shipping_cost_per_unit[request.warehouse_id],
                landed_unit_cost=ranked.landed_unit_cost,
                total_cost=ranked.landed_unit_cost * request.quantity,
                cost_vs_cheapest_pct=100.0 * (ranked.landed_unit_cost / cheapest - 1.0),
                lead_time_days=offer.lead_time_days,
                lead_time_vs_fastest_days=offer.lead_time_days - fastest,
                reliability=supplier.reliability,
                quality_score=supplier.quality_score,
                capacity_headroom=_component(ranked, Criterion.CAPACITY),
                contract_fit=_component(ranked, Criterion.CONTRACT_FIT),
            )
        )
    leaders = tuple(CriterionLeader(criterion=c, supplier_id=_leader(rows, c)) for c in Criterion)
    return SupplierComparison(
        request=request, rows=tuple(rows), leaders=leaders, trade_offs=_trade_offs(rows)
    )


def source_suppliers(
    request: SourcingRequest, catalog: SourcingCatalog, weights: RankingWeights | None = None
) -> SourcingResult:
    weights = weights or RankingWeights()
    decisions = evaluate_eligibility(request, catalog)
    eligible_ids = {d.offer_id for d in decisions if d.eligible}
    offers = [o for o in catalog.offers_for_sku(request.sku_id) if o.offer_id in eligible_ids]
    ranking = rank_offers(offers, request, catalog, weights)
    counts = Counter(r.reason for d in decisions for r in d.rejections)
    return SourcingResult(
        request=request,
        weights=weights,
        decisions=tuple(decisions),
        rejection_counts={
            reason.value: counts[reason] for reason in RejectionReason if counts[reason]
        },
        ranking=tuple(ranking),
        comparison=build_comparison(request, ranking, catalog),
    )
