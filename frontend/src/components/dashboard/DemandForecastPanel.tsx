"use client";

import { useMemo, useState } from "react";
import { Notice, Panel, ResourceView, Stat } from "@/components/ui";
import { TimeSeriesChart } from "@/components/TimeSeriesChart";
import type { ForecastBandPoint, HistoryPoint } from "@/components/TimeSeriesChart";
import { getDemand, getForecast, nextWeekStart } from "@/lib/api/planning";
import type { DemandPoint, ForecastResponse } from "@/lib/api/types";
import { formatInt } from "@/lib/format";
import { useSession } from "@/lib/session";
import { useResource } from "@/lib/useResource";

const ALL = "ALL";
const HISTORY_WEEKS = 26;
const HORIZON_WEEKS = 8;

interface Loaded {
  demand: DemandPoint[];
  forecasts: ForecastResponse[];
}

/** Sums the weekly demand of the chosen region (or all regions) into one series, oldest first. */
export function weeklyHistory(demand: DemandPoint[], region: string): HistoryPoint[] {
  const totals = new Map<string, number>();
  for (const point of demand) {
    if (region !== ALL && point.regionId !== region) continue;
    totals.set(point.periodStart, (totals.get(point.periodStart) ?? 0) + point.quantity);
  }
  return [...totals.entries()]
    .sort(([a], [b]) => a.localeCompare(b))
    .slice(-HISTORY_WEEKS)
    .map(([date, value]) => ({ date, value }));
}

/**
 * The forecast of one region with its interval, or all regions summed. Intervals are per region and cannot
 * be added, so the caller must not draw the summed lower/upper as an interval.
 */
export function forecastBand(forecasts: ForecastResponse[], region: string): ForecastBandPoint[] {
  const chosen = region === ALL ? forecasts : forecasts.filter((f) => f.regionId === region);
  const byWeek = new Map<string, ForecastBandPoint>();
  for (const forecast of chosen) {
    for (const p of forecast.points) {
      const current = byWeek.get(p.weekStart);
      byWeek.set(p.weekStart, {
        date: p.weekStart,
        point: (current?.point ?? 0) + p.point,
        lower: (current?.lower ?? 0) + p.lower,
        upper: (current?.upper ?? 0) + p.upper,
      });
    }
  }
  const band = [...byWeek.values()].sort((a, b) => a.date.localeCompare(b.date));
  return band;
}

export function DemandForecastPanel({ skuId }: { skuId: string }) {
  const { user, ready } = useSession();
  const [region, setRegion] = useState(ALL);
  const { state, reload } = useResource<Loaded>(ready ? `${user.userId}:${skuId}` : null, async (signal) => {
    const demand = await getDemand(skuId, 52, signal);
    if (demand.length === 0) return { demand, forecasts: [] };
    const lastWeek = demand.reduce((max, p) => (p.periodStart > max ? p.periodStart : max), "");
    const asOf = nextWeekStart(lastWeek);
    const regions = [...new Set(demand.map((p) => p.regionId))].sort();
    const forecasts = await Promise.all(
      regions.map((regionId) => getForecast(skuId, regionId, asOf, HORIZON_WEEKS)),
    );
    return { demand, forecasts };
  });

  return (
    <Panel title="Demand and forecast" id="demand-forecast">
      <ResourceView state={state} onRetry={reload} loadingLabel="Loading demand and forecast…">
        {(data) => <Body data={data} region={region} onRegion={setRegion} />}
      </ResourceView>
    </Panel>
  );
}

function Body({
  data,
  region,
  onRegion,
}: {
  data: Loaded;
  region: string;
  onRegion: (region: string) => void;
}) {
  const regions = useMemo(
    () => [...new Set(data.demand.map((p) => p.regionId))].sort(),
    [data.demand],
  );
  const history = useMemo(() => weeklyHistory(data.demand, region), [data.demand, region]);
  const band = useMemo(() => forecastBand(data.forecasts, region), [data.forecasts, region]);
  if (data.demand.length === 0) return <p className="muted">No demand history for this SKU.</p>;

  const recent = history.slice(-HORIZON_WEEKS).reduce((sum, p) => sum + p.value, 0);
  const upcoming = band.reduce((sum, p) => sum + p.point, 0);
  const model = data.forecasts[0];
  const intervalLevel = region === ALL ? undefined : model?.intervalLevel;

  return (
    <div className="stack">
      <div className="row">
        <label className="field">
          <span>Region</span>
          <select value={region} onChange={(e) => onRegion(e.target.value)}>
            <option value={ALL}>All regions</option>
            {regions.map((r) => (
              <option key={r} value={r}>
                {r}
              </option>
            ))}
          </select>
        </label>
        {model ? (
          <span className="muted">
            Model {model.modelVersion} · forecast from {model.asOf}
          </span>
        ) : null}
      </div>
      <dl className="stats">
        <Stat label={`Last ${HORIZON_WEEKS} weeks`} value={formatInt(recent)} hint="units sold" />
        <Stat
          label={`Next ${band.length} weeks`}
          value={formatInt(upcoming)}
          hint="forecast units"
        />
      </dl>
      {region === ALL ? (
        <Notice>
          Prediction intervals are per region and cannot be added together, so the all-regions view shows
          the point forecast only. Pick a region to see its interval.
        </Notice>
      ) : null}
      <TimeSeriesChart
        history={history}
        forecast={band}
        intervalLevel={intervalLevel}
        showBand={region !== ALL}
      />
    </div>
  );
}
