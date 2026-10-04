import { Notice, Stat } from "@/components/ui";
import { scenarioLabel } from "@/lib/scenarios";
import type { ScenarioComparison } from "@/lib/api/types";
import {
  formatInt,
  formatMoney,
  formatPercent,
  formatSignedMoney,
  formatSignedPercentPoints,
} from "@/lib/format";

export function ScenarioComparisonView({ comparison: c }: { comparison: ScenarioComparison }) {
  return (
    <div className="stack">
      <h3>{scenarioLabel(c.scenarioType)}</h3>
      <div>
        <h4 style={{ margin: "0 0 4px" }}>What changed</h4>
        {c.assumptionsChanged.length === 0 ? (
          <p className="muted">This test doesn&apos;t change anything in the plan.</p>
        ) : (
          <ul>
            {c.assumptionsChanged.map((a) => (
              <li key={a}>{a}</li>
            ))}
          </ul>
        )}
      </div>
      <dl className="stats">
        <Stat label="Cost of the current plan" value={formatMoney(c.baselineObjective)} />
        <Stat
          label="Cost if we keep the plan"
          value={formatSignedMoney(c.disruptedObjectiveDelta)}
          hint="baseline plan, disrupted world"
        />
        <Stat
          label="Cost if we re-plan"
          value={formatSignedMoney(c.responseObjectiveDelta)}
          hint="plan re-optimized"
        />
        <Stat label="Extra cost vs. the current plan" value={formatMoney(c.resilienceCost)} hint="what the disruption costs" />
        <Stat label="Saved by re-planning" value={formatMoney(c.responseBenefit)} hint="saved by responding" />
      </dl>
      <dl className="stats">
        <Stat
          label="Demand covered if we keep the plan"
          value={formatSignedPercentPoints(c.serviceDeltaDisrupted)}
        />
        <Stat
          label="Demand covered if we re-plan"
          value={formatSignedPercentPoints(c.serviceDeltaResponse)}
          hint={`${formatPercent(c.baselineCustomerFillRate)} → ${formatPercent(c.responseCustomerFillRate)} fill`}
        />
        <Stat label="Order lines changed" value={formatInt(c.changedPurchaseLines)} />
      </dl>
      {c.newlyBinding.length > 0 ? (
        <Notice tone="warn">Limits now reached: {c.newlyBinding.join("; ")}.</Notice>
      ) : null}
      {c.supplierShifts.length > 0 ? (
        <div className="table-scroll">
          <table>
            <caption className="muted" style={{ textAlign: "left" }}>
              Biggest supplier changes after re-planning
            </caption>
            <thead>
              <tr>
                <th>Supplier</th>
                <th className="num">Units now</th>
                <th className="num">Units after re-planning</th>
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
