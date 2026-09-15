-- Feedback loop (docs/feedback-loop.md): what a decision relied on and what actually happened.
-- Recommendations, approvals, decisions and purchase orders already exist (V1, V4). These tables add
-- the forecast an approved recommendation relied on and the realised outcomes. All of them are
-- append-only: a correction is a new row, and the latest row for a key is the one that counts.

CREATE TABLE forecast_snapshot (
    snapshot_id       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recommendation_id text NOT NULL REFERENCES recommendation (recommendation_id),
    model_version     text NOT NULL,
    dataset_id        text NOT NULL,
    sku_id            text NOT NULL REFERENCES sku (sku_id),
    region_id         text NOT NULL REFERENCES region (region_id),
    as_of             date NOT NULL,
    week_start        date NOT NULL,
    horizon           integer NOT NULL CHECK (horizon >= 1),
    point             numeric(14, 3) NOT NULL CHECK (point >= 0),
    lower_bound       numeric(14, 3) NOT NULL CHECK (lower_bound >= 0),
    upper_bound       numeric(14, 3) NOT NULL CHECK (upper_bound >= lower_bound),
    interval_level    numeric(4, 3) NOT NULL CHECK (interval_level > 0 AND interval_level < 1),
    recorded_at       timestamptz NOT NULL DEFAULT now(),
    UNIQUE (recommendation_id, sku_id, region_id, week_start)
);
CREATE INDEX forecast_snapshot_series ON forecast_snapshot (sku_id, region_id, week_start);

CREATE TABLE outcome_demand (
    outcome_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sku_id      text NOT NULL REFERENCES sku (sku_id),
    region_id   text NOT NULL REFERENCES region (region_id),
    week_start  date NOT NULL CHECK (extract(isodow FROM week_start) = 1),
    quantity    numeric(14, 2) NOT NULL CHECK (quantity >= 0),
    source      text NOT NULL CHECK (source IN ('RECORDED', 'SIMULATED')),
    recorded_by text NOT NULL,
    recorded_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX outcome_demand_key ON outcome_demand (sku_id, region_id, week_start, outcome_id DESC);

CREATE TABLE outcome_delivery (
    outcome_id         bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    po_id              text NOT NULL REFERENCES purchase_order (po_id),
    delivered_on       date NOT NULL,
    delivered_quantity integer NOT NULL CHECK (delivered_quantity >= 0),
    source             text NOT NULL CHECK (source IN ('RECORDED', 'SIMULATED')),
    recorded_by        text NOT NULL,
    recorded_at        timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX outcome_delivery_po ON outcome_delivery (po_id, outcome_id DESC);

CREATE TABLE outcome_inventory (
    outcome_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    sku_id       text NOT NULL REFERENCES sku (sku_id),
    warehouse_id text NOT NULL REFERENCES warehouse (warehouse_id),
    week_start   date NOT NULL CHECK (extract(isodow FROM week_start) = 1),
    on_hand      integer NOT NULL CHECK (on_hand >= 0),
    unmet_units  integer NOT NULL DEFAULT 0 CHECK (unmet_units >= 0),
    source       text NOT NULL CHECK (source IN ('RECORDED', 'SIMULATED')),
    recorded_by  text NOT NULL,
    recorded_at  timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX outcome_inventory_key ON outcome_inventory (sku_id, warehouse_id, week_start, outcome_id DESC);

CREATE TRIGGER forecast_snapshot_append_only
    BEFORE UPDATE OR DELETE ON forecast_snapshot
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER outcome_demand_append_only
    BEFORE UPDATE OR DELETE ON outcome_demand
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER outcome_delivery_append_only
    BEFORE UPDATE OR DELETE ON outcome_delivery
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
CREATE TRIGGER outcome_inventory_append_only
    BEFORE UPDATE OR DELETE ON outcome_inventory
    FOR EACH ROW EXECUTE FUNCTION forbid_mutation();
