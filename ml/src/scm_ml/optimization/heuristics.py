from __future__ import annotations

import math
from collections import defaultdict
from enum import StrEnum

from scm_common.domain import PurchaseLine, SupplierOffer
from scm_ml.sourcing import SourcingCatalog, SourcingRequest, rank_offers

from .problem import ProcurementProblem


class SupplierChoice(StrEnum):
    CHEAPEST = "cheapest"
    WEIGHTED = "weighted"


def _landed(offer: SupplierOffer, warehouse_id: str) -> float:
    return offer.unit_price + offer.shipping_cost_per_unit[warehouse_id]


def reorder_up_to(
    problem: ProcurementProblem,
    catalog: SourcingCatalog,
    choice: SupplierChoice = SupplierChoice.CHEAPEST,
) -> list[PurchaseLine]:
    remaining_capacity: dict[str, int] = defaultdict(int)
    lines: list[PurchaseLine] = []
    for key, cell in problem.cells.items():
        need = math.ceil(cell.demand + cell.safety_stock - cell.available)
        offers = list(problem.offers.get(key, ()))
        if need <= 0 or not offers:
            continue
        if choice is SupplierChoice.WEIGHTED:
            request = SourcingRequest(
                sku_id=key.sku_id,
                warehouse_id=key.warehouse_id,
                quantity=need,
                as_of=problem.as_of,
                max_lead_time_days=problem.params.lead_time_limit,
                horizon_weeks=problem.params.horizon_weeks,
            )
            by_id = {o.offer_id: o for o in offers}
            order = [by_id[r.offer_id] for r in rank_offers(offers, request, catalog)]
        else:
            order = sorted(offers, key=lambda o: (_landed(o, key.warehouse_id), o.supplier_id))
        for offer in order:
            if need <= 0:
                break
            if offer.offer_id not in remaining_capacity:
                remaining_capacity[offer.offer_id] = problem.max_units(offer)
            room = remaining_capacity[offer.offer_id]
            quantity = min(max(need, offer.moq), room)
            if quantity < offer.moq:
                continue
            remaining_capacity[offer.offer_id] -= quantity
            need -= quantity
            lines.append(
                PurchaseLine(
                    supplier_id=offer.supplier_id,
                    sku_id=key.sku_id,
                    warehouse_id=key.warehouse_id,
                    quantity=quantity,
                    unit_price=offer.unit_price,
                    shipping_cost=round(
                        offer.shipping_cost_per_unit[key.warehouse_id] * quantity, 4
                    ),
                )
            )
    return lines
