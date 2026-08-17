import { Notice } from "@/components/ui";
import type { SupplierSearchResult } from "@/lib/api/types";
import { formatInt, formatMoney, formatPercent, formatUnitPrice, humanize } from "@/lib/format";

/** The engine's ranked, comparable supplier options and why the others were rejected. */
export function SupplierResults({ result }: { result: SupplierSearchResult }) {
  const rejected = Object.entries(result.rejected);
  const cheapest = result.cheapestOverall;
  return (
    <div className="stack">
      {cheapest && !cheapest.eligible ? (
        <Notice tone="warn">
          The cheapest supplier overall ({cheapest.supplierId}, {formatUnitPrice(cheapest.landedUnitCost)} per
          unit landed) is not eligible: {cheapest.rejectionReasons.map(humanize).join(", ")}.
        </Notice>
      ) : null}
      {result.ranked.length === 0 ? (
        <Notice tone="bad">
          No supplier is eligible for {formatInt(result.quantity)} units of {result.skuId} at{" "}
          {result.warehouseId}.
        </Notice>
      ) : (
        <div className="table-scroll">
          <table>
            <caption className="muted" style={{ textAlign: "left" }}>
              {result.eligibleCount} eligible, showing the top {result.ranked.length}
            </caption>
            <thead>
              <tr>
                <th>Rank</th>
                <th>Supplier</th>
                <th className="num">Landed cost / unit</th>
                <th className="num">Total</th>
                <th className="num">vs cheapest</th>
                <th className="num">Lead time</th>
                <th className="num">Reliability</th>
                <th className="num">Quality</th>
              </tr>
            </thead>
            <tbody>
              {result.ranked.map((r) => (
                <tr key={r.supplierId}>
                  <td>{r.rank}</td>
                  <td>
                    {r.supplierName} <span className="muted">({r.supplierId})</span>
                  </td>
                  <td className="num">{formatUnitPrice(r.landedUnitCost)}</td>
                  <td className="num">{formatMoney(r.totalCost)}</td>
                  <td className="num">{r.costVsCheapestPct > 0 ? `+${r.costVsCheapestPct}%` : "cheapest"}</td>
                  <td className="num">{r.leadTimeDays} d</td>
                  <td className="num">{formatPercent(r.reliability)}</td>
                  <td className="num">{formatPercent(r.qualityScore)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {result.tradeOffs.length > 0 ? (
        <div>
          <h3>Trade-offs</h3>
          <ul>
            {result.tradeOffs.map((t) => (
              <li key={t}>{t}</li>
            ))}
          </ul>
        </div>
      ) : null}
      {rejected.length > 0 ? (
        <details>
          <summary>{rejected.length} suppliers rejected</summary>
          <ul>
            {rejected.map(([supplierId, reasons]) => (
              <li key={supplierId}>
                {supplierId}: {reasons.map(humanize).join(", ")}
              </li>
            ))}
          </ul>
        </details>
      ) : null}
    </div>
  );
}
