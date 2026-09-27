import { Badge, Notice, Stat } from "@/components/ui";
import type { PlanResult, PlanSpec } from "@/lib/api/types";
import {
  formatInt,
  formatMoney,
  formatPercent,
  formatUnitPrice,
  humanize,
} from "@/lib/format";

const SOLVER_STATUS_TEXT: Record<string, string> = {
  OPTIMAL: "Best possible plan found",
  LIMIT_REACHED: "Good plan, search stopped at the time limit",
  INFEASIBLE: "No plan can meet all the limits",
  UNBOUNDED: "The problem is not set up correctly",
  ERROR: "The calculation failed",
};

export function PlanAssumptions({ spec, plan }: { spec: PlanSpec; plan: PlanResult }) {
  return (
    <dl className="kv">
      <dt>Products</dt>
      <dd>{spec.skuIds.join(", ")}</dd>
      <dt>Planning period</dt>
      <dd>{plan.horizonWeeks} weeks</dd>
      <dt>Demand</dt>
      <dd>
        forecast × {plan.demandMultiplier}
        {plan.demandMultiplier === 1 ? " (as forecast)" : ""}
      </dd>
      <dt>Share of demand to cover</dt>
      <dd>{formatPercent(plan.serviceLevelTarget, 0)}</dd>
      <dt>Budget</dt>
      <dd>{plan.budget === null ? "none" : formatMoney(plan.budget)}</dd>
      <dt>Optimizer result</dt>
      <dd title={plan.solverStatus}>{SOLVER_STATUS_TEXT[plan.solverStatus] ?? plan.solverStatus}</dd>
    </dl>
  );
}

export function PlanView({
  plan,
  onAlternatives,
}: {
  plan: PlanResult;
  onAlternatives?: (line: PlanResult["lines"][number]) => void;
}) {
  return (
    <div className="stack">
      <dl className="stats">
        <Stat label="Total cost (incl. shortage penalties)" value={formatMoney(plan.objective)} />
        <Stat label="Order value" value={formatMoney(plan.orderValue)} hint={`${plan.orders} orders`} />
        <Stat
          label="Demand covered by the plan"
          value={formatPercent(plan.fillRate)}
          hint={`${formatInt(plan.unmetDemand)} of ${formatInt(plan.totalDemand)} units unmet`}
        />
        <Stat label="Customer orders filled" value={formatPercent(plan.customerFillRate)} />
      </dl>

      {plan.violations.length > 0 ? (
        <Notice tone="bad">
          This plan breaks constraints:{" "}
          {plan.violations.map((v) => `${humanize(v.kind)} (${v.subject})`).join("; ")}.
        </Notice>
      ) : (
        <p>
          <Badge tone="good">Meets every limit</Badge>
        </p>
      )}

      <div>
        <h3>What to buy</h3>
        {plan.lines.length === 0 ? (
          <p className="muted">The plan buys nothing.</p>
        ) : (
          <div className="table-scroll">
            <table>
              <thead>
                <tr>
                  <th>Supplier</th>
                  <th>SKU</th>
                  <th>Warehouse</th>
                  <th className="num">Quantity</th>
                  <th className="num">Unit price</th>
                  <th className="num">Value</th>
                  {onAlternatives ? <th /> : null}
                </tr>
              </thead>
              <tbody>
                {plan.lines.map((line) => (
                  <tr key={`${line.supplierId}-${line.skuId}-${line.warehouseId}`}>
                    <td>{line.supplierId}</td>
                    <td>{line.skuId}</td>
                    <td>{line.warehouseId}</td>
                    <td className="num">{formatInt(line.quantity)}</td>
                    <td className="num">{formatUnitPrice(line.unitPrice)}</td>
                    <td className="num">{formatMoney(line.value)}</td>
                    {onAlternatives ? (
                      <td>
                        <button
                          type="button"
                          className="link-button"
                          onClick={() => onAlternatives(line)}
                          aria-label={`Alternatives for ${line.skuId} at ${line.warehouseId}`}
                        >
                          Alternatives
                        </button>
                      </td>
                    ) : null}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <div className="grid-2">
        <div>
          <h3>Spend by supplier</h3>
          <ul>
            {plan.bySupplier.map((s) => (
              <li key={s.supplierId}>
                {s.supplierId}: {formatInt(s.units)} units, {formatMoney(s.spend)}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3>Limits it comes closest to</h3>
          {plan.bindingConstraints.length === 0 ? (
            <p className="muted">None reported.</p>
          ) : (
            <ul>
              {plan.bindingConstraints.map((c) => (
                <li key={`${c.kind}-${c.subject}`}>
                  {humanize(c.kind)} {c.subject}: {formatPercent(c.utilization, 0)} used
                </li>
              ))}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
