-- Core planning workflow schema. Mirrors src/scm_common/domain (see docs/domain-schema.md).

CREATE TABLE region (
    region_id text PRIMARY KEY,
    name      text NOT NULL
);

CREATE TABLE sku (
    sku_id                  text PRIMARY KEY,
    name                    text NOT NULL,
    category                text NOT NULL,
    unit_price              numeric(12, 2) NOT NULL CHECK (unit_price > 0),
    unit_volume             numeric(10, 3) NOT NULL CHECK (unit_volume > 0),
    required_certifications text[] NOT NULL DEFAULT '{}'
);

CREATE TABLE supplier (
    supplier_id    text PRIMARY KEY,
    name           text NOT NULL,
    region_id      text NOT NULL REFERENCES region (region_id),
    reliability    numeric(4, 3) NOT NULL CHECK (reliability BETWEEN 0 AND 1),
    quality_score  numeric(4, 3) NOT NULL CHECK (quality_score BETWEEN 0 AND 1),
    certifications text[] NOT NULL DEFAULT '{}'
);
CREATE INDEX supplier_certifications_gin ON supplier USING gin (certifications);

CREATE TABLE warehouse (
    warehouse_id               text PRIMARY KEY,
    name                       text NOT NULL,
    region_id                  text NOT NULL REFERENCES region (region_id),
    capacity_units             numeric(14, 2) NOT NULL CHECK (capacity_units > 0),
    holding_cost_per_unit_week numeric(8, 3) NOT NULL CHECK (holding_cost_per_unit_week >= 0)
);

CREATE TABLE fulfillment_lane (
    warehouse_id  text NOT NULL REFERENCES warehouse (warehouse_id),
    region_id     text NOT NULL REFERENCES region (region_id),
    cost_per_unit numeric(8, 3) NOT NULL CHECK (cost_per_unit >= 0),
    transit_days  integer NOT NULL CHECK (transit_days >= 0),
    PRIMARY KEY (warehouse_id, region_id)
);

CREATE TABLE supplier_contract (
    contract_id        text PRIMARY KEY,
    supplier_id        text NOT NULL REFERENCES supplier (supplier_id),
    status             text NOT NULL CHECK (status IN ('ACTIVE', 'EXPIRED', 'SUSPENDED')),
    effective_from     date NOT NULL,
    effective_to       date NOT NULL,
    payment_terms_days integer NOT NULL CHECK (payment_terms_days >= 0),
    max_order_value    numeric(14, 2) CHECK (max_order_value > 0),
    CHECK (effective_to >= effective_from)
);
CREATE INDEX supplier_contract_supplier_status ON supplier_contract (supplier_id, status);

CREATE TABLE supplier_offer (
    offer_id          text PRIMARY KEY,
    supplier_id       text NOT NULL REFERENCES supplier (supplier_id),
    sku_id            text NOT NULL REFERENCES sku (sku_id),
    unit_price        numeric(12, 2) NOT NULL CHECK (unit_price > 0),
    moq               integer NOT NULL CHECK (moq >= 1),
    capacity_per_week integer NOT NULL CHECK (capacity_per_week >= 1),
    lead_time_days    integer NOT NULL CHECK (lead_time_days >= 0),
    valid_from        date NOT NULL,
    valid_to          date NOT NULL,
    CHECK (valid_to >= valid_from)
);
-- main query path: eligible offers for a SKU on a date
CREATE INDEX supplier_offer_sku_validity ON supplier_offer (sku_id, valid_from, valid_to);
CREATE INDEX supplier_offer_supplier ON supplier_offer (supplier_id);

CREATE TABLE supplier_offer_shipping (
    offer_id      text NOT NULL REFERENCES supplier_offer (offer_id) ON DELETE CASCADE,
    warehouse_id  text NOT NULL REFERENCES warehouse (warehouse_id),
    cost_per_unit numeric(8, 3) NOT NULL CHECK (cost_per_unit >= 0),
    PRIMARY KEY (offer_id, warehouse_id)
);

CREATE TABLE sales_order (
    order_id   text PRIMARY KEY,
    sku_id     text NOT NULL REFERENCES sku (sku_id),
    region_id  text NOT NULL REFERENCES region (region_id),
    ordered_at timestamptz NOT NULL,
    quantity   integer NOT NULL CHECK (quantity >= 1)
);
CREATE INDEX sales_order_series ON sales_order (sku_id, region_id, ordered_at);

-- Demand is source-qualified (synthetic world and the public dataset use different SKU spaces),
-- so there are deliberately no foreign keys on sku_id / region_id here.
CREATE TABLE demand_observation (
    source       text NOT NULL,
    sku_id       text NOT NULL,
    region_id    text NOT NULL,
    period_start date NOT NULL,
    quantity     numeric(14, 2) NOT NULL CHECK (quantity >= 0),
    observed_at  timestamptz NOT NULL,
    PRIMARY KEY (source, sku_id, region_id, period_start)
);
CREATE INDEX demand_observation_period ON demand_observation (source, period_start);

CREATE TABLE inventory_position (
    sku_id       text NOT NULL REFERENCES sku (sku_id),
    warehouse_id text NOT NULL REFERENCES warehouse (warehouse_id),
    as_of        timestamptz NOT NULL,
    on_hand      integer NOT NULL CHECK (on_hand >= 0),
    incoming     integer NOT NULL CHECK (incoming >= 0),
    safety_stock integer NOT NULL CHECK (safety_stock >= 0),
    PRIMARY KEY (sku_id, warehouse_id, as_of)
);
CREATE INDEX inventory_position_warehouse ON inventory_position (warehouse_id, as_of);

CREATE TABLE scenario (
    scenario_id   text PRIMARY KEY,
    name          text NOT NULL,
    scenario_type text NOT NULL CHECK (scenario_type IN (
        'DEMAND_SHOCK', 'SUPPLIER_OUTAGE', 'PRICE_SHOCK', 'CAPACITY_REDUCTION',
        'LEAD_TIME_SHOCK', 'WAREHOUSE_CAPACITY_REDUCTION', 'TRANSPORT_COST_SHOCK')),
    parameters    jsonb NOT NULL DEFAULT '{}',
    created_at    timestamptz NOT NULL
);

CREATE TABLE recommendation (
    recommendation_id      text PRIMARY KEY,
    created_at             timestamptz NOT NULL,
    summary                text NOT NULL,
    objective_value        numeric(16, 2) NOT NULL,
    expected_service_level numeric(5, 4) NOT NULL CHECK (expected_service_level BETWEEN 0 AND 1),
    assumptions            jsonb NOT NULL DEFAULT '[]',
    citations              jsonb NOT NULL DEFAULT '[]',
    scenario_id            text REFERENCES scenario (scenario_id),
    horizon_start          date NOT NULL,
    horizon_end            date NOT NULL,
    status                 text NOT NULL DEFAULT 'PROPOSED'
        CHECK (status IN ('PROPOSED', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED')),
    CHECK (horizon_end >= horizon_start)
);
CREATE INDEX recommendation_status_created ON recommendation (status, created_at DESC);

CREATE TABLE recommendation_line (
    recommendation_id text NOT NULL REFERENCES recommendation (recommendation_id) ON DELETE CASCADE,
    line_no           integer NOT NULL,
    supplier_id       text NOT NULL REFERENCES supplier (supplier_id),
    sku_id            text NOT NULL REFERENCES sku (sku_id),
    warehouse_id      text NOT NULL REFERENCES warehouse (warehouse_id),
    quantity          integer NOT NULL CHECK (quantity >= 1),
    unit_price        numeric(12, 2) NOT NULL CHECK (unit_price > 0),
    shipping_cost     numeric(14, 2) NOT NULL CHECK (shipping_cost >= 0),
    PRIMARY KEY (recommendation_id, line_no)
);

CREATE TABLE purchase_order (
    po_id              text PRIMARY KEY,
    supplier_id        text NOT NULL REFERENCES supplier (supplier_id),
    sku_id             text NOT NULL REFERENCES sku (sku_id),
    warehouse_id       text NOT NULL REFERENCES warehouse (warehouse_id),
    quantity           integer NOT NULL CHECK (quantity >= 1),
    unit_price         numeric(12, 2) NOT NULL CHECK (unit_price > 0),
    status             text NOT NULL CHECK (status IN (
        'DRAFT', 'PENDING_APPROVAL', 'APPROVED', 'REJECTED', 'PLACED', 'DELIVERED')),
    created_at         timestamptz NOT NULL,
    expected_delivery  date NOT NULL,
    delivered_at       date,
    delivered_quantity integer CHECK (delivered_quantity >= 0),
    recommendation_id  text REFERENCES recommendation (recommendation_id)
);
CREATE INDEX purchase_order_supplier_created ON purchase_order (supplier_id, created_at);
CREATE INDEX purchase_order_sku_created ON purchase_order (sku_id, created_at);
CREATE INDEX purchase_order_status ON purchase_order (status);

-- Decisions are an immutable audit trail.
CREATE TABLE decision (
    decision_id       text PRIMARY KEY,
    recommendation_id text NOT NULL REFERENCES recommendation (recommendation_id),
    decided_by        text NOT NULL,
    outcome           text NOT NULL CHECK (outcome IN ('APPROVED', 'REJECTED')),
    decided_at        timestamptz NOT NULL,
    rationale         text
);
CREATE INDEX decision_recommendation ON decision (recommendation_id);

CREATE FUNCTION forbid_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION '% on % is not allowed: table is append-only', TG_OP, TG_TABLE_NAME;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER decision_append_only
    BEFORE UPDATE OR DELETE ON decision
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
