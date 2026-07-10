# Domain schema

Source of truth: `src/scm_common/domain/` (pydantic models). All models are immutable, reject unknown
fields, use explicit string IDs, and require timezone-aware timestamps (normalised to UTC). Dates
without a time (`period_start`, `effective_from`, …) are plain calendar dates.

| Concept | Model | Key fields |
|---|---|---|
| Region | `Region` | `region_id`, `name` |
| SKU | `Sku` | `sku_id`, `category`, `unit_price`, `unit_volume`, `required_certifications` |
| Supplier | `Supplier` | `supplier_id`, `region_id`, `reliability`, `quality_score`, `certifications` |
| Warehouse | `Warehouse` | `warehouse_id`, `region_id`, `capacity_units`, `holding_cost_per_unit_week` |
| Contract (structured) | `SupplierContract` | `contract_id`, `supplier_id`, `status`, `effective_from/to`, `payment_terms_days` |
| Supplier offer | `SupplierOffer` | `offer_id`, `supplier_id`, `sku_id`, `unit_price`, `moq`, `capacity_per_week`, `lead_time_days`, `shipping_cost_per_unit` |
| Customer order line | `SalesOrder` | `order_id`, `sku_id`, `region_id`, `ordered_at`, `quantity` |
| Demand observation | `DemandObservation` | `sku_id`, `region_id`, `period_start`, `quantity`, `source`, `observed_at` |
| Inventory position | `InventoryPosition` | `sku_id`, `warehouse_id`, `as_of`, `on_hand`, `incoming`, `safety_stock` |
| Purchase order | `PurchaseOrder` | `po_id`, `supplier_id`, `sku_id`, `warehouse_id`, `quantity`, `status`, `expected_delivery`, `delivered_at` |
| Contract/policy document | `PolicyDocument` | `document_id`, `doc_type`, `version`, `effective_date`, `expiry_date`, `allowed_roles` |
| Scenario | `Scenario` | `scenario_id`, `scenario_type`, `parameters` |
| Recommendation | `Recommendation` | `recommendation_id`, `lines`, `objective_value`, `expected_service_level`, `citations`, `status` |
| Decision | `Decision` | `decision_id`, `recommendation_id`, `decided_by`, `outcome`, `decided_at` |

## Design notes

- `DemandObservation.observed_at` records when a value became known. Forecast datasets use it as the
  leakage guard: a feature may only use observations whose `observed_at` precedes the forecast origin.
- `PolicyDocument` carries version, effective/expiry dates and `allowed_roles`, which the RAG layer
  uses for staleness and permission filtering.
- `Decision` is an audit record of a human decision; `Recommendation.status` tracks the approval
  workflow (`PROPOSED` → `PENDING_APPROVAL` → `APPROVED`/`REJECTED`).
- Supplier-level shipping cost is stored per destination warehouse on the offer, so shipping cost is
  a property of a (supplier, SKU, warehouse) route.
