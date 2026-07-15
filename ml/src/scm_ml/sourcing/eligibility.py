from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import Field

from scm_common.domain import ContractStatus, DomainModel, SupplierContract, SupplierOffer

from .catalog import SourcingCatalog, SourcingRequest


class SourcingError(ValueError): ...


class RejectionReason(StrEnum):
    NO_OFFER_FOR_SKU = "NO_OFFER_FOR_SKU"
    OFFER_NOT_VALID = "OFFER_NOT_VALID"
    REGION_NOT_SERVED = "REGION_NOT_SERVED"
    SUPPLIER_REGION_EXCLUDED = "SUPPLIER_REGION_EXCLUDED"
    BELOW_MOQ = "BELOW_MOQ"
    EXCEEDS_CAPACITY = "EXCEEDS_CAPACITY"
    LEAD_TIME_TOO_LONG = "LEAD_TIME_TOO_LONG"
    MISSING_CERTIFICATION = "MISSING_CERTIFICATION"
    NO_CONTRACT = "NO_CONTRACT"
    CONTRACT_EXPIRED = "CONTRACT_EXPIRED"
    CONTRACT_SUSPENDED = "CONTRACT_SUSPENDED"
    ORDER_VALUE_EXCEEDS_CONTRACT = "ORDER_VALUE_EXCEEDS_CONTRACT"


class Rejection(DomainModel):
    reason: RejectionReason
    detail: str = Field(min_length=1)


class EligibilityDecision(DomainModel):
    supplier_id: str
    offer_id: str | None = Field(description="None when the supplier has no offer for the SKU.")
    eligible: bool
    rejections: tuple[Rejection, ...] = ()


def contract_in_force(contract: SupplierContract, as_of: date) -> bool:
    return contract.status == ContractStatus.ACTIVE and contract.effective_from <= as_of <= (
        contract.effective_to
    )


def max_order_value(contracts: tuple[SupplierContract, ...], as_of: date) -> float | None:
    limits = [c.max_order_value for c in contracts if contract_in_force(c, as_of)]
    if not limits or any(limit is None for limit in limits):
        return None
    return max(limit for limit in limits if limit is not None)


def _contract_rejection(contracts: tuple[SupplierContract, ...], as_of: date) -> Rejection | None:
    if not contracts:
        return Rejection(reason=RejectionReason.NO_CONTRACT, detail="supplier has no contract")
    if not any(contract_in_force(c, as_of) for c in contracts):
        if any(c.status == ContractStatus.SUSPENDED for c in contracts):
            return Rejection(
                reason=RejectionReason.CONTRACT_SUSPENDED, detail="contract is suspended"
            )
        return Rejection(
            reason=RejectionReason.CONTRACT_EXPIRED,
            detail=f"no active contract covers {as_of.isoformat()}",
        )
    return None


def structural_rejections(
    offer: SupplierOffer,
    catalog: SourcingCatalog,
    *,
    as_of: date,
    warehouse_id: str,
    max_lead_time_days: int,
) -> list[Rejection]:
    supplier = catalog.suppliers[offer.supplier_id]
    sku = catalog.skus[offer.sku_id]
    found: list[Rejection] = []
    if not offer.valid_from <= as_of <= offer.valid_to:
        found.append(
            Rejection(
                reason=RejectionReason.OFFER_NOT_VALID,
                detail=f"offer valid {offer.valid_from} to {offer.valid_to}, decision date {as_of}",
            )
        )
    if warehouse_id not in offer.shipping_cost_per_unit:
        found.append(
            Rejection(
                reason=RejectionReason.REGION_NOT_SERVED,
                detail=f"no shipping lane to {warehouse_id}",
            )
        )
    if offer.lead_time_days > max_lead_time_days:
        found.append(
            Rejection(
                reason=RejectionReason.LEAD_TIME_TOO_LONG,
                detail=f"lead time {offer.lead_time_days}d exceeds limit {max_lead_time_days}d",
            )
        )
    missing = sorted(set(sku.required_certifications) - set(supplier.certifications))
    if missing:
        found.append(
            Rejection(
                reason=RejectionReason.MISSING_CERTIFICATION,
                detail=f"missing certification: {', '.join(missing)}",
            )
        )
    contract = _contract_rejection(catalog.contracts.get(offer.supplier_id, ()), as_of)
    if contract is not None:
        found.append(contract)
    return found


def _offer_rejections(
    offer: SupplierOffer, request: SourcingRequest, catalog: SourcingCatalog
) -> list[Rejection]:
    supplier = catalog.suppliers[offer.supplier_id]
    found = structural_rejections(
        offer,
        catalog,
        as_of=request.as_of,
        warehouse_id=request.warehouse_id,
        max_lead_time_days=request.max_lead_time_days,
    )
    allowed = request.allowed_supplier_regions
    if allowed is not None and supplier.region_id not in allowed:
        found.append(
            Rejection(
                reason=RejectionReason.SUPPLIER_REGION_EXCLUDED,
                detail=f"supplier ships from {supplier.region_id}, allowed: {', '.join(allowed)}",
            )
        )
    if request.quantity < offer.moq:
        found.append(
            Rejection(
                reason=RejectionReason.BELOW_MOQ,
                detail=f"quantity {request.quantity} is below MOQ {offer.moq}",
            )
        )
    available = offer.capacity_per_week * request.horizon_weeks
    if request.quantity > available:
        found.append(
            Rejection(
                reason=RejectionReason.EXCEEDS_CAPACITY,
                detail=f"quantity {request.quantity} exceeds capacity {available} "
                f"({offer.capacity_per_week}/week x {request.horizon_weeks} weeks)",
            )
        )
    limit = max_order_value(catalog.contracts.get(offer.supplier_id, ()), request.as_of)
    value = request.quantity * offer.unit_price
    if limit is not None and value > limit:
        found.append(
            Rejection(
                reason=RejectionReason.ORDER_VALUE_EXCEEDS_CONTRACT,
                detail=f"order value {value:.2f} exceeds contract limit {limit:.2f}",
            )
        )
    return found


def evaluate_eligibility(
    request: SourcingRequest, catalog: SourcingCatalog
) -> list[EligibilityDecision]:
    if request.sku_id not in catalog.skus:
        raise SourcingError(f"unknown SKU {request.sku_id}")
    if request.warehouse_id not in catalog.warehouses:
        raise SourcingError(f"unknown warehouse {request.warehouse_id}")

    offers_by_supplier = {o.supplier_id: o for o in catalog.offers_for_sku(request.sku_id)}
    decisions: list[EligibilityDecision] = []
    for supplier_id in sorted(catalog.suppliers):
        offer = offers_by_supplier.get(supplier_id)
        if offer is None:
            decisions.append(
                EligibilityDecision(
                    supplier_id=supplier_id,
                    offer_id=None,
                    eligible=False,
                    rejections=(
                        Rejection(
                            reason=RejectionReason.NO_OFFER_FOR_SKU,
                            detail=f"supplier does not offer {request.sku_id}",
                        ),
                    ),
                )
            )
            continue
        rejections = _offer_rejections(offer, request, catalog)
        decisions.append(
            EligibilityDecision(
                supplier_id=supplier_id,
                offer_id=offer.offer_id,
                eligible=not rejections,
                rejections=tuple(rejections),
            )
        )
    return decisions


def eligible_offers(request: SourcingRequest, catalog: SourcingCatalog) -> list[SupplierOffer]:
    ids = {d.offer_id for d in evaluate_eligibility(request, catalog) if d.eligible}
    return [o for o in catalog.offers_for_sku(request.sku_id) if o.offer_id in ids]
