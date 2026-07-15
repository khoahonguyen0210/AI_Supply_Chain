from __future__ import annotations

from enum import StrEnum

from pydantic import Field, model_validator

from scm_common.domain import DomainModel, SupplierContract, SupplierOffer

from .catalog import SourcingCatalog, SourcingRequest
from .eligibility import contract_in_force

PAYMENT_TERMS_REFERENCE_DAYS = 60.0
"""Payment terms at or above this many days earn full credit for the terms half of contract fit."""


class Criterion(StrEnum):
    COST = "COST"
    LEAD_TIME = "LEAD_TIME"
    RELIABILITY = "RELIABILITY"
    CAPACITY = "CAPACITY"
    QUALITY = "QUALITY"
    CONTRACT_FIT = "CONTRACT_FIT"


class RankingWeights(DomainModel):
    cost: float = Field(default=0.35, ge=0)
    lead_time: float = Field(default=0.15, ge=0)
    reliability: float = Field(default=0.20, ge=0)
    capacity: float = Field(default=0.10, ge=0)
    quality: float = Field(default=0.10, ge=0)
    contract_fit: float = Field(default=0.10, ge=0)

    @model_validator(mode="after")
    def _sum_to_one(self) -> RankingWeights:
        total = self.total()
        if abs(total - 1.0) > 1e-9:
            raise ValueError(f"weights must sum to 1, got {total}")
        return self

    def total(self) -> float:
        return (
            self.cost
            + self.lead_time
            + self.reliability
            + self.capacity
            + self.quality
            + self.contract_fit
        )

    def weight_of(self, criterion: Criterion) -> float:
        return float(getattr(self, criterion.value.lower()))


class ScoreComponent(DomainModel):
    criterion: Criterion
    raw_value: float = Field(description="Value in the criterion's natural unit.")
    normalized: float = Field(ge=0, le=1, description="1 is best among the eligible suppliers.")
    weight: float = Field(ge=0, le=1)
    contribution: float = Field(ge=0, le=1, description="weight x normalized.")


class RankedOffer(DomainModel):
    rank: int = Field(ge=1)
    supplier_id: str
    offer_id: str
    score: float = Field(ge=0, le=1)
    landed_unit_cost: float = Field(gt=0, description="Unit price plus shipping to the warehouse.")
    components: tuple[ScoreComponent, ...]


def contract_fit(
    contracts: tuple[SupplierContract, ...], request: SourcingRequest, order_value: float
) -> float:
    in_force = [c for c in contracts if contract_in_force(c, request.as_of)]
    if not in_force:
        return 0.0
    terms = max(min(c.payment_terms_days / PAYMENT_TERMS_REFERENCE_DAYS, 1.0) for c in in_force)
    headrooms = [
        1.0 if c.max_order_value is None else max(0.0, 1.0 - order_value / c.max_order_value)
        for c in in_force
    ]
    return 0.5 * terms + 0.5 * max(headrooms)


def landed_unit_cost(offer: SupplierOffer, warehouse_id: str) -> float:
    return offer.unit_price + offer.shipping_cost_per_unit[warehouse_id]


def _raw_values(
    offer: SupplierOffer, request: SourcingRequest, catalog: SourcingCatalog
) -> dict[Criterion, float]:
    supplier = catalog.suppliers[offer.supplier_id]
    order_value = request.quantity * offer.unit_price
    return {
        Criterion.COST: landed_unit_cost(offer, request.warehouse_id),
        Criterion.LEAD_TIME: float(offer.lead_time_days),
        Criterion.RELIABILITY: supplier.reliability,
        Criterion.CAPACITY: offer.capacity_per_week * request.horizon_weeks / request.quantity,
        Criterion.QUALITY: supplier.quality_score,
        Criterion.CONTRACT_FIT: contract_fit(
            catalog.contracts.get(offer.supplier_id, ()), request, order_value
        ),
    }


LOWER_IS_BETTER = {Criterion.COST, Criterion.LEAD_TIME}


def _normalize(criterion: Criterion, values: list[float]) -> list[float]:
    low, high = min(values), max(values)
    if high == low:
        return [1.0] * len(values)  # no differentiation: nobody is penalised
    span = high - low
    if criterion in LOWER_IS_BETTER:
        return [(high - v) / span for v in values]
    return [(v - low) / span for v in values]


def rank_offers(
    offers: list[SupplierOffer],
    request: SourcingRequest,
    catalog: SourcingCatalog,
    weights: RankingWeights | None = None,
) -> list[RankedOffer]:
    """Best first; ties break on supplier id so the output is deterministic."""
    if not offers:
        return []
    weights = weights or RankingWeights()
    raw = [_raw_values(o, request, catalog) for o in offers]
    normalized = {c: _normalize(c, [r[c] for r in raw]) for c in Criterion}
    scored: list[tuple[float, str, RankedOffer]] = []
    for i, offer in enumerate(offers):
        components = tuple(
            ScoreComponent(
                criterion=c,
                raw_value=raw[i][c],
                normalized=normalized[c][i],
                weight=weights.weight_of(c),
                contribution=weights.weight_of(c) * normalized[c][i],
            )
            for c in Criterion
        )
        score = min(1.0, sum(c.contribution for c in components))
        scored.append(
            (
                score,
                offer.supplier_id,
                RankedOffer(
                    rank=1,
                    supplier_id=offer.supplier_id,
                    offer_id=offer.offer_id,
                    score=score,
                    landed_unit_cost=raw[i][Criterion.COST],
                    components=components,
                ),
            )
        )
    scored.sort(key=lambda t: (-round(t[0], 12), t[1]))
    return [t[2].model_copy(update={"rank": n}) for n, t in enumerate(scored, start=1)]


def cheapest_first(offers: list[SupplierOffer], warehouse_id: str) -> list[SupplierOffer]:
    return sorted(offers, key=lambda o: (landed_unit_cost(o, warehouse_id), o.supplier_id))
