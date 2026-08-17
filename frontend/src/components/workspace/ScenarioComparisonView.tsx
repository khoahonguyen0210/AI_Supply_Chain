import { Notice, Stat } from "@/components/ui";
import type { ScenarioComparison } from "@/lib/api/types";
import {
  formatInt,
  formatMoney,
  formatPercent,
  formatSignedMoney,
  formatSignedPercentPoints,
  humanize,
} from "@/lib/format";

/**
 * Baseline, disrupted and re-optimized outcomes of one scenario. "Disrupted" is the baseline purchase plan
 * held fixed in the disrupted world; "response" is the plan re-optimized for it.
 */
export function ScenarioComparisonView({ comparison: c }: { comparison: ScenarioComparison }) {
  return (
    <div className="stack">
      <h3>{humanize(c.scenarioType)}</h3>
      <div>
        <h4 style={{ margin: "0 0 4px" }}>What changed</h4>
        {c.assumptionsChanged.length === 0 ? (
          <p className="muted">No assumption changed; this scenario does not touch the plan&apos;s inputs.</p>
        ) : (
          <ul>
            {c.assumptionsChanged.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        )}
      </div>
      <dl className="stats">
        <Stat label="Baseline cost" value={formatMoney(c.baselineObjective)} />
        <Stat
          label="Cost if nothing changes"
          value={formatSignedMoney(c.disruptedObjectiveDelta)}
          hint="baseline plan, disrupted world"
        />
        <Stat
          label="Cost after re-planning"
          value={formatSignedMoney(c.responseObjectiveDelta)}
          hint="plan re-optimized"
        />
        <Stat label="Resilience cost" value={formatMoney(c.resilienceCost)} hint="what the disruption costs" />
        <Stat label="Re-planning benefit" value={formatMoney(c.responseBenefit)} hint="saved by responding" />
      </dl>
      <dl className="stats">
        <Stat
          label="Service if nothing changes"
          value={formatSignedPercentPoints(c.serviceDeltaDisrupted)}
        />
        <Stat
          label="Service after re-planning"
          value={formatSignedPercentPoints(c.serviceDeltaResponse)}
          hint={`${formatPercent(c.baselineCustomerFillRate)} → ${formatPercent(c.responseCustomerFillRate)} fill`}
        />
        <Stat label="Purchase lines changed" value={formatInt(c.changedPurchaseLines)} />
      </dl>
      {c.newlyBinding.length > 0 ? (
        <Notice tone="warn">Constraints that become binding: {c.newlyBinding.join("; ")}.</Notice>
      ) : null}
      {c.supplierShifts.length > 0 ? (
        <div className="table-scroll">
          <table>
            <caption className="muted" style={{ textAlign: "left" }}>
              Largest supplier shifts after re-planning
            </caption>
            <thead>
              <tr>
                <th>Supplier</th>
                <th className="num">Baseline units</th>
                <th className="num">Response units</th>
              </tr>
            </thead>
            <tbody>
              {c.supplierShifts.map((s) => (
                <tr key={s.supplierId}>
                  <td>{s.supplierId}</td>
                  <td className="num">{formatInt(s.baselineUnits)}</td>
                  <td className="num">{formatInt(s.responseUnits)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : null}
    </div>
  );
}
