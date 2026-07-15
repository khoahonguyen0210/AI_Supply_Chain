# Supplier sourcing

Code: `ml/src/scm_ml/sourcing/`. Pipeline: Search -> Eligibility -> Ranking -> Comparison. Ranking is not the
final decision; the optimizer (Phase 5) chooses quantities under constraints.

Entry point: `source_suppliers(request, catalog, weights=None) -> SourcingResult`.
A `SourcingRequest` is one SKU, one destination warehouse, a quantity, a decision date (`as_of`), a
maximum lead time and a capacity horizon in weeks.

## Eligibility

Every supplier is evaluated and every failing rule is reported (not just the first), each as a
`RejectionReason` with a human-readable detail.

| Reason | Rule |
|---|---|
| `NO_OFFER_FOR_SKU` | supplier has no offer for the product |
| `OFFER_NOT_VALID` | `as_of` outside the offer's validity window |
| `REGION_NOT_SERVED` | offer has no shipping lane to the destination warehouse |
| `SUPPLIER_REGION_EXCLUDED` | supplier region not in `allowed_supplier_regions` |
| `BELOW_MOQ` | quantity < MOQ |
| `EXCEEDS_CAPACITY` | quantity > `capacity_per_week x horizon_weeks` |
| `LEAD_TIME_TOO_LONG` | offer lead time > `max_lead_time_days` |
| `MISSING_CERTIFICATION` | supplier lacks a certification the SKU requires |
| `NO_CONTRACT` / `CONTRACT_EXPIRED` / `CONTRACT_SUSPENDED` | no ACTIVE contract covering `as_of` |
| `ORDER_VALUE_EXCEEDS_CONTRACT` | quantity x unit price above the contract's `max_order_value` |

## Ranking

Each criterion is min-max normalised across the eligible offers to [0, 1] (1 = best; cost and lead time
are inverted; a criterion with no spread gives everyone 1). Score = sum of weight x normalised value.
Default weights: cost 0.35, lead time 0.15, reliability 0.20, capacity 0.10, quality 0.10, contract fit
0.10 (must sum to 1). Cost is landed unit cost (price + shipping to the warehouse). Capacity is available
capacity / requested quantity. Contract fit is half payment terms (capped at 60 days), half headroom
under the order-value limit. Ties break on supplier id, so output is deterministic. Each `RankedOffer`
stores its `ScoreComponent`s (raw value, normalised value, weight, contribution).

## Comparison

`SupplierComparison` has one row per eligible supplier (price, shipping, landed cost, % over cheapest,
lead time, days slower than fastest, reliability, quality, capacity headroom, contract fit), the leader
per criterion, and plain-language trade-off statements for the top-ranked supplier.
`cheapest_first` is the naive baseline for the sourcing evaluation (cheapest vs weighted vs optimized).
