from __future__ import annotations

import hashlib
import json
import urllib.request
import zipfile
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from scm_common.domain import DemandObservation, DomainModel

SOURCE_NAME = "uci-online-retail-ii"
SOURCE_URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
SOURCE_ZIP_SHA256 = "572e36277c2390fbfde10664750731e0a86f55e33470d91919085f0408e67bfb"
ZIP_NAME = "online_retail_ii.zip"
XLSX_NAME = "online_retail_II.xlsx"
CACHE_NAME = "transactions.csv.gz"
RAW_COLUMNS = ["Invoice", "StockCode", "Description", "Quantity", "InvoiceDate", "Price", "Country"]
PRODUCT_CODE = r"^\d{5}[A-Za-z]{0,2}$"  # excludes POST, DOT, M, BANK CHARGES, ...
OTHER_REGION = "OTHER"
TRANSFORM_VERSION = "1"


class OnlineRetailConfig(DomainModel):
    n_skus: int = 40
    n_regions: int = 5  # top (n_regions - 1) countries plus OTHER
    min_active_weeks: int = 20
    # Series are picked from data before this date, so validation/test weeks can't sway them.
    selection_cutoff: date = date(2011, 6, 6)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def fetch_raw(raw_dir: Path) -> Path:
    raw_dir.mkdir(parents=True, exist_ok=True)
    archive = raw_dir / ZIP_NAME
    if not archive.exists():
        urllib.request.urlretrieve(SOURCE_URL, archive)  # noqa: S310 - fixed https URL
    actual = sha256_file(archive)
    if actual != SOURCE_ZIP_SHA256:
        raise ValueError(f"{ZIP_NAME} checksum {actual} does not match pinned {SOURCE_ZIP_SHA256}")
    xlsx = raw_dir / "extracted" / XLSX_NAME
    if not xlsx.exists():
        with zipfile.ZipFile(archive) as bundle:
            bundle.extract(XLSX_NAME, raw_dir / "extracted")
    return xlsx


def load_raw_transactions(raw_dir: Path) -> pd.DataFrame:
    """Unique transactions; the sheets overlap on 2010-12-01..09, where the second wins."""
    cache = raw_dir / CACHE_NAME
    if cache.exists():
        return pd.read_csv(
            cache, dtype={"Invoice": str, "StockCode": str}, parse_dates=["InvoiceDate"]
        )
    xlsx = fetch_raw(raw_dir)
    sheets = pd.read_excel(
        xlsx,
        sheet_name=None,
        engine="openpyxl",
        usecols=RAW_COLUMNS,
        dtype={"Invoice": str, "StockCode": str},
    )
    first, second = sheets["Year 2009-2010"], sheets["Year 2010-2011"]
    frame: pd.DataFrame = pd.concat(
        [first[first["InvoiceDate"] < second["InvoiceDate"].min()], second], ignore_index=True
    )
    frame.to_csv(cache, index=False)
    return frame


def _clean(raw: pd.DataFrame) -> pd.DataFrame:
    frame = raw[RAW_COLUMNS].copy()
    frame["StockCode"] = frame["StockCode"].astype(str).str.strip().str.upper()
    frame["Invoice"] = frame["Invoice"].astype(str)
    keep = (
        frame["StockCode"].str.match(PRODUCT_CODE)
        & ~frame["Invoice"].str.startswith("C")  # cancellations
        & (frame["Quantity"] > 0)
        & (frame["Price"] > 0)
    )
    return frame[keep].reset_index(drop=True)


def normalize_transactions(
    raw: pd.DataFrame, cfg: OnlineRetailConfig
) -> tuple[pd.DataFrame, pd.DataFrame]:
    full_span = raw["InvoiceDate"]
    first_day, last_day = full_span.min().normalize(), full_span.max().normalize()
    frame = _clean(raw)
    frame["week_start"] = frame["InvoiceDate"].dt.normalize() - pd.to_timedelta(
        frame["InvoiceDate"].dt.weekday, unit="D"
    )
    # keep only weeks completely covered by the data
    weeks = pd.date_range(
        first_day + pd.Timedelta(days=(7 - first_day.weekday()) % 7), last_day, freq="W-MON"
    )
    weeks = weeks[weeks + pd.Timedelta(days=6) <= last_day]
    frame = frame[frame["week_start"].isin(weeks)]

    cutoff = pd.Timestamp(cfg.selection_cutoff)
    before = frame[frame["week_start"] < cutoff]

    country_units = before.groupby("Country")["Quantity"].sum()
    top_countries = sorted(
        country_units.sort_values(ascending=False, kind="stable").index[: cfg.n_regions - 1]
    )
    frame = frame.assign(
        region_id=frame["Country"].where(frame["Country"].isin(top_countries), OTHER_REGION)
    )
    before = frame[frame["week_start"] < cutoff]

    sku_stats = before.groupby("StockCode").agg(
        units=("Quantity", "sum"), active_weeks=("week_start", "nunique")
    )
    eligible = sku_stats[sku_stats["active_weeks"] >= cfg.min_active_weeks]
    selected = (
        eligible.reset_index()
        .sort_values(["units", "StockCode"], ascending=[False, True], kind="stable")
        .head(cfg.n_skus)["StockCode"]
        .tolist()
    )
    frame = frame[frame["StockCode"].isin(selected)]

    weekly = frame.groupby(["StockCode", "region_id", "week_start"])["Quantity"].sum()
    regions = sorted({*top_countries, OTHER_REGION})
    grid = pd.MultiIndex.from_product(
        [sorted(selected), regions, weeks], names=["StockCode", "region_id", "week_start"]
    )
    demand = weekly.reindex(grid, fill_value=0).rename("quantity").reset_index()
    demand["sku_id"] = demand["StockCode"]
    demand["period_start"] = demand["week_start"].dt.date
    demand["quantity"] = demand["quantity"].astype("int64")
    demand["source"] = SOURCE_NAME
    demand["observed_at"] = (demand["week_start"] + pd.Timedelta(days=7)).dt.strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    demand = demand[["sku_id", "region_id", "period_start", "quantity", "source", "observed_at"]]

    meta = (
        frame.groupby("StockCode")
        .agg(
            description=("Description", lambda s: s.mode().iat[0] if not s.mode().empty else ""),
            median_price=("Price", "median"),
        )
        .reindex(sorted(selected))
        .reset_index()
        .rename(columns={"StockCode": "sku_id"})
    )
    return demand, meta


def to_observations(demand: pd.DataFrame) -> list[DemandObservation]:
    return [
        DemandObservation(
            sku_id=str(row.sku_id),
            region_id=str(row.region_id),
            period_start=row.period_start,
            quantity=float(str(row.quantity)),
            source=str(row.source),
            observed_at=datetime.fromisoformat(
                str(row.observed_at).replace("Z", "+00:00")
            ).astimezone(UTC),
        )
        for row in demand.itertuples(index=False)
    ]


def build_dataset(
    raw_dir: Path, out_dir: Path, cfg: OnlineRetailConfig | None = None
) -> dict[str, Any]:
    cfg = cfg or OnlineRetailConfig()
    raw = load_raw_transactions(raw_dir)
    demand, meta = normalize_transactions(raw, cfg)
    out_dir.mkdir(parents=True, exist_ok=True)
    demand.to_csv(out_dir / "demand_weekly.csv", index=False, lineterminator="\n")
    meta.to_csv(out_dir / "skus.csv", index=False, lineterminator="\n")
    files = {
        name: {"rows": len(frame), "sha256": sha256_file(out_dir / name)}
        for name, frame in (("demand_weekly.csv", demand), ("skus.csv", meta))
    }
    config = cfg.model_dump(mode="json")
    identity = hashlib.sha256(
        json.dumps(
            {"files": files, "config": config, "source": SOURCE_ZIP_SHA256}, sort_keys=True
        ).encode()
    ).hexdigest()
    manifest: dict[str, Any] = {
        "dataset_id": f"{SOURCE_NAME}-v{TRANSFORM_VERSION}-{identity[:12]}",
        "source": {
            "name": SOURCE_NAME,
            "url": SOURCE_URL,
            "archive_sha256": SOURCE_ZIP_SHA256,
            "raw_rows_after_sheet_dedup": len(raw),
            "license": "CC BY 4.0",
        },
        "transform_version": TRANSFORM_VERSION,
        "config": config,
        "first_week": str(demand["period_start"].min()),
        "last_week": str(demand["period_start"].max()),
        "files": files,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8"
    )
    return manifest
