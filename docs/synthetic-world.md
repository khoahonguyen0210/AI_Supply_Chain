# Synthetic SCM world

Generate: `uv run python -m scm_ml.synthetic --out data/synthetic --seed 42`
(output is git-ignored; the generator is deterministic, so it is always reproducible).

| Item | Value |
|---|---|
| SKUs / suppliers / warehouses / regions | 40 / 10 / 3 / 5 |
| History | 104 weeks from 2023-01-02 (24 months); planning date (`as_of`) 2024-12-30 |
| Customer order lines | ~20,000 (19,980 at seed 42) |
| Supplier offers | ~200, each with MOQ, weekly capacity, lead time, per-warehouse shipping cost |
| Historical purchase orders | ~1,800, with on-time/short-delivery behaviour driven by supplier reliability |

## Encoded constraints

- **MOQ, capacity, lead time, cost** per supplier offer; cheaper suppliers are slower and less reliable.
- **Certifications**: electronics need RoHS, food HACCP, industrial ISO9001; offers exist only from certified suppliers.
- **Contracts**: the last two suppliers have an EXPIRED and a SUSPENDED contract (eligibility must reject them).
- **Warehouse capacity**: sized so current stock fills ~50%; **shipping**: warehouse-to-region lanes by distance.
- **Demand**: SKU popularity (Zipf-like), regional weights, category seasonality, per-SKU trend and two promo weeks. Weekly demand per SKU-region is intermittent (~half of cell-weeks are zero), so MAPE is only valid on non-zero actuals.

## Determinism and identity

A single seed drives three independent random streams (master data, demand, operations). `manifest.json`
records config, per-file row counts and SHA-256 checksums, and a `dataset_id` derived from them.
`read_world` refuses a directory whose files no longer match the manifest.

`validate_world` checks id uniqueness, referential integrity, certification coverage, capacity >= MOQ,
>=3 active offers per SKU, history window, and warehouse stock <= capacity.
