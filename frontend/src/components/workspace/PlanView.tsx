import { Badge, Notice, Stat } from "@/components/ui";
import type { PlanResult, PlanSpec } from "@/lib/api/types";
import {
  formatInt,
  formatMoney,
  formatPercent,
  formatUnitPrice,
  humanize,
} from "@/lib/format";

/** What the optimizer assumed: the inputs the planner chose plus the solver's own status. */
export function PlanAssumptions({ spec, plan }: { spec: PlanSpec; plan: PlanResult }) {
  return (
    <dl className="kv">
      <dt>Products</dt>
      <dd>{spec.skuIds.join(", ")}</dd>
      <dt>Horizon</dt>
      <dd>{plan.horizonWeeks} weeks</dd>
      <dt>Demand</dt>
      <dd>
        forecast × {plan.demandMultiplier}
        {plan.demandMultiplier === 1 ? " (no adjustment)" : ""}
      </dd>
      <dt>Service level target</dt>
      <dd>{formatPercent(plan.serviceLevelTarget, 0)}</dd>
      <dt>Budget</dt>
      <dd>{plan.budget === null ? "none" : formatMoney(plan.budget)}</dd>
      <dt>Solver</dt>
      <dd>{plan.solverStatus}</dd>
    </dl>
  );
}

/** The optimizer's output: objective, service, violations, the purchase lines and what constrains them. */
export function PlanView({
  plan,
  onAlternatives,
}: {
  plan: PlanResult;
  /** Offered for each purchase line so the planner can look at the other suppliers. */
  onAlternatives?: (line: PlanResult["lines"][number]) => void;
}) {
  return (
    <div className="stack">
      <dl className="stats">
        <Stat label="Objective (total cost)" value={formatMoney(plan.objective)} />
        <Stat label="Order value" value={formatMoney(plan.orderValue)} hint={`${plan.orders} orders`} />
        <Stat
          label="Demand covered"
          value={formatPercent(plan.fillRate)}
          hint={`${formatInt(plan.unmetDemand)} of ${formatInt(plan.totalDemand)} units unmet`}
        />
        <Stat label="Customer fill rate" value={formatPercent(plan.customerFillRate)} />
      </dl>

      {plan.violations.length > 0 ? (
        <Notice tone="bad">
          This plan breaks constraints:{" "}
          {plan.violations.map((v) => `${humanize(v.kind)} (${v.subject})`).join("; ")}.
        </Notice>
      ) : (
        <p>
          <Badge tone="good">All constraints satisfied</Badge>
        </p>
      )}

      <div>
        <h3>Purchase lines</h3>
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
          <h3>Constraints closest to binding</h3>
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
