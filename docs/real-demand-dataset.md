# Real demand dataset: UCI Online Retail II

The Research Dossier requires a public real-world demand dataset but does not name one. Chosen under
the "simplest production-sensible option" rule: **UCI Online Retail II**
(https://archive.ics.uci.edu/dataset/502/online+retail+ii, CC BY 4.0) - real transactions of a UK online
retailer, 2009-12-01 to 2011-12-09. It downloads without a login and has SKU, country and timestamp.

Build: `uv run python -m scm_ml.realdata` (downloads, verifies the pinned SHA-256, normalises).
Output (git-ignored): `data/real_demand/{demand_weekly.csv, skus.csv, manifest.json}`.

## Source identity

- Archive SHA-256 is pinned in code (`SOURCE_ZIP_SHA256`); a mismatch aborts ingestion.
- The workbook has two sheets that overlap on 2010-12-01..09. The overlap was verified identical
  (22,523 rows each), and the second sheet is used for it: 1,044,848 unique transactions remain.
- `manifest.json` records source URL/hash, config, per-file row counts and checksums, and a
  `dataset_id` derived from them.

## Normalisation

1. Keep product stock codes only (drop POST, DOT, M, BANK CHARGES, ...); drop cancellations
   (`Invoice` starting with `C`), non-positive quantity or price. Customer IDs are never loaded.
2. Weekly (Monday-start) units per SKU x region; only weeks fully covered by the data are kept
   (2009-12-07 .. 2011-11-28, 104 weeks). Missing SKU-region-weeks are zero-filled.
3. Regions: the 4 countries with the most units + `OTHER`. Series: the 40 SKUs with the most units
   (min. 20 active weeks).
4. `observed_at` = end of the week, matching the `DemandObservation` schema.

## No future leakage

SKU and region selection uses only weeks **before `selection_cutoff` (2011-06-06)**, the planned start
of the forecast validation window (train < 2011-06-06; validation 2011-06-06 .. 2011-09-04; test from
2011-09-05, 13 weeks each). A test rewrites all post-cutoff data and asserts the selection is unchanged.

## Characteristics

20,800 rows; ~66% of SKU-region-weeks are zero (non-UK regions are sparse), so MAPE is only defined on
non-zero actuals and MAE/RMSE/bias are the primary metrics.
