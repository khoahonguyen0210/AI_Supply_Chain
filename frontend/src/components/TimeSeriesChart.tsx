import { formatDate, formatNumber } from "@/lib/format";

export interface HistoryPoint {
  date: string;
  value: number;
}

export interface ForecastBandPoint {
  date: string;
  point: number;
  lower: number;
  upper: number;
}

const WIDTH = 720;
const HEIGHT = 260;
const PAD = { top: 12, right: 12, bottom: 28, left: 48 };

/**
 * Demand history as a line, the forecast as a dashed line with its prediction interval as a band. Dates are
 * placed by their real time, so a gap between history and forecast shows as a gap.
 */
export function TimeSeriesChart({
  history,
  forecast,
  intervalLevel,
  showBand = true,
  unitLabel = "units / week",
}: {
  history: HistoryPoint[];
  forecast: ForecastBandPoint[];
  intervalLevel?: number;
  /** False when the forecast has no meaningful interval (for example summed regions). */
  showBand?: boolean;
  unitLabel?: string;
}) {
  const times = [...history.map((p) => p.date), ...forecast.map((p) => p.date)].map(
    (d) => new Date(`${d}T00:00:00Z`).getTime(),
  );
  if (times.length === 0) return <p className="muted">No data to chart.</p>;

  const minT = Math.min(...times);
  const maxT = Math.max(...times);
  const values = [
    ...history.map((p) => p.value),
    ...forecast.flatMap((p) => (showBand ? [p.lower, p.point, p.upper] : [p.point])),
  ];
  const maxV = Math.max(1, ...values);
  const innerW = WIDTH - PAD.left - PAD.right;
  const innerH = HEIGHT - PAD.top - PAD.bottom;
  const x = (date: string) =>
    PAD.left +
    (maxT === minT
      ? innerW / 2
      : ((new Date(`${date}T00:00:00Z`).getTime() - minT) / (maxT - minT)) * innerW);
  const y = (value: number) => PAD.top + innerH - (value / maxV) * innerH;

  const line = (points: { date: string; v: number }[]) =>
    points.map((p, i) => `${i === 0 ? "M" : "L"}${x(p.date).toFixed(1)},${y(p.v).toFixed(1)}`).join(" ");
  const historyPath = line(history.map((p) => ({ date: p.date, v: p.value })));
  const forecastPath = line(forecast.map((p) => ({ date: p.date, v: p.point })));
  const band =
    showBand && forecast.length > 0
      ? [
          ...forecast.map((p) => `${x(p.date).toFixed(1)},${y(p.upper).toFixed(1)}`),
          ...[...forecast]
            .reverse()
            .map((p) => `${x(p.date).toFixed(1)},${y(p.lower).toFixed(1)}`),
        ].join(" ")
      : "";

  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => f * maxV);
  const first = history[0]?.date ?? forecast[0].date;
  const last = forecast[forecast.length - 1]?.date ?? history[history.length - 1].date;
  const summary =
    `Weekly demand ${history.length > 0 ? `from ${formatDate(first)}` : ""}` +
    (forecast.length > 0
      ? `, forecast to ${formatDate(last)}${showBand && intervalLevel ? ` with ${Math.round(intervalLevel * 100)}% interval` : ""}`
      : "");

  return (
    <figure className="chart">
      <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} role="img" aria-label={summary}>
        {ticks.map((t) => (
          <g key={t}>
            <line className="chart-grid" x1={PAD.left} x2={WIDTH - PAD.right} y1={y(t)} y2={y(t)} />
            <text className="chart-label" x={PAD.left - 6} y={y(t) + 4} textAnchor="end">
              {formatNumber(t)}
            </text>
          </g>
        ))}
        {band ? <polygon className="chart-band" points={band} /> : null}
        {history.length > 0 ? <path className="chart-history" d={historyPath} fill="none" /> : null}
        {forecast.length > 0 ? (
          <path className="chart-forecast" d={forecastPath} fill="none" />
        ) : null}
        <text className="chart-label" x={PAD.left} y={HEIGHT - 8}>
          {formatDate(first)}
        </text>
        <text className="chart-label" x={WIDTH - PAD.right} y={HEIGHT - 8} textAnchor="end">
          {formatDate(last)}
        </text>
      </svg>
      <figcaption className="chart-legend">
        <span className="legend-item legend-history">Demand</span>
        {forecast.length > 0 ? (
          <>
            <span className="legend-item legend-forecast">Forecast</span>
            {showBand ? (
              <span className="legend-item legend-band">
                {intervalLevel ? `${Math.round(intervalLevel * 100)}% interval` : "Interval"}
              </span>
            ) : null}
          </>
        ) : null}
        <span className="muted">{unitLabel}</span>
      </figcaption>
    </figure>
  );
}
