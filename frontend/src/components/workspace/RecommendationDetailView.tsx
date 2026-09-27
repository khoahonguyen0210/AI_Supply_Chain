"use client";

import Link from "next/link";
import { Citations } from "@/components/Citations";
import { Badge, Panel, ResourceView, Stat, StatusBadge } from "@/components/ui";
import { getRecommendation } from "@/lib/api/decisions";
import type { RecommendationDetail } from "@/lib/api/types";
import {
  formatDate,
  formatDateTime,
  formatInt,
  formatMoney,
  formatPercent,
  formatUnitPrice,
  humanize,
} from "@/lib/format";
import { useSession } from "@/lib/session";
import { useResource } from "@/lib/useResource";

export function RecommendationBody({ detail }: { detail: RecommendationDetail }) {
  const { recommendation: r, lines, approval, decisions } = detail;
  const orderValue = lines.reduce((sum, l) => sum + l.quantity * l.unitPrice, 0);
  const shipping = lines.reduce((sum, l) => sum + l.shippingCost, 0);
  return (
    <div className="stack">
      <Panel title="Recommendation" id="recommendation">
        <p style={{ marginTop: 0 }}>{r.summary}</p>
        <dl className="stats">
          <Stat label="Status" value={<StatusBadge status={r.status} />} />
          <Stat label="Total cost (incl. shortage penalties)" value={formatMoney(r.objectiveValue)} />
          <Stat label="Expected demand covered" value={formatPercent(r.expectedServiceLevel)} />
          <Stat label="Order value" value={formatMoney(orderValue)} hint={`+ ${formatMoney(shipping)} shipping`} />
        </dl>
        <p className="muted">
          Horizon {formatDate(r.horizonStart)} to {formatDate(r.horizonEnd)} · prepared{" "}
          {formatDateTime(r.createdAt)}
        </p>
      </Panel>

      <div className="grid-2">
        <Panel title="Assumptions" id="assumptions">
          {r.assumptions.length === 0 ? (
            <p className="muted">No assumptions were recorded.</p>
          ) : (
            <ul>
              {r.assumptions.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          )}
        </Panel>
        <Panel title="Sources" id="evidence">
          <Citations citations={r.citations} />
        </Panel>
      </div>

      <Panel title="What to buy" id="lines">
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Supplier</th>
                <th>SKU</th>
                <th>Warehouse</th>
                <th className="num">Quantity</th>
                <th className="num">Unit price</th>
                <th className="num">Shipping</th>
              </tr>
            </thead>
            <tbody>
              {lines.map((l) => (
                <tr key={l.lineNo}>
                  <td>{l.supplierId}</td>
                  <td>{l.skuId}</td>
                  <td>{l.warehouseId}</td>
                  <td className="num">{formatInt(l.quantity)}</td>
                  <td className="num">{formatUnitPrice(l.unitPrice)}</td>
                  <td className="num">{formatMoney(l.shippingCost)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </Panel>

      <Panel
        title="Approval"
        id="approval"
        actions={
          approval ? <Link href={`/approvals?open=${encodeURIComponent(approval.approvalId)}`}>Open in approvals</Link> : null
        }
      >
        {approval === null ? (
          <p className="muted">No approval has been requested for this recommendation.</p>
        ) : (
          <div className="stack">
            <p style={{ margin: 0 }}>
              <StatusBadge status={approval.status} /> requested by {approval.requestedBy} (
              {humanize(approval.requesterRole)}), order value {formatMoney(approval.orderValue)}
            </p>
            <p style={{ margin: 0 }}>
              Required approvals:{" "}
              {approval.requiredRoles.map((role) => (
                <Badge key={role} tone={approval.approvedRoles.includes(role) ? "good" : "warn"}>
                  {humanize(role)} {approval.approvedRoles.includes(role) ? "approved" : "needed"}
                </Badge>
              ))}
            </p>
            {decisions.length > 0 ? (
              <ul>
                {decisions.map((d) => (
                  <li key={d.decisionId}>
                    {formatDateTime(d.decidedAt)}: {d.decidedBy} ({humanize(d.approverRole)}){" "}
                    {d.outcome.toLowerCase()}
                    {d.rationale ? ` — ${d.rationale}` : ""}
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        )}
      </Panel>
    </div>
  );
}

export function RecommendationDetailView({ id }: { id: string }) {
  const { user, ready } = useSession();
  const { state, reload } = useResource(ready ? `${user.userId}:${id}` : null, (signal) =>
    getRecommendation(id, signal),
  );
  return (
    <div className="stack">
      <div>
        <p>
          <Link href="/workspace">← Plan builder</Link>
        </p>
        <h1>Recommendation {id}</h1>
      </div>
      <ResourceView state={state} onRetry={reload} loadingLabel="Loading recommendation…">
        {(detail) => <RecommendationBody detail={detail} />}
      </ResourceView>
    </div>
  );
}
