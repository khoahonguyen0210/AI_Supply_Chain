"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { ApprovalActions } from "@/components/ApprovalActions";
import { Badge, EmptyState, Notice, Panel, ResourceView, StatusBadge } from "@/components/ui";
import { getApproval, listApprovals } from "@/lib/api/decisions";
import type { ApprovalDetail, ApprovalStatus } from "@/lib/api/types";
import {
  formatDateTime,
  formatInt,
  formatMoney,
  formatUnitPrice,
  humanize,
} from "@/lib/format";
import { useSession } from "@/lib/session";
import { useResource } from "@/lib/useResource";

export function ApprovalBody({
  detail,
  onDecided,
}: {
  detail: ApprovalDetail;
  onDecided: (detail: ApprovalDetail) => void;
}) {
  const { approval, recommendation, decisions } = detail;
  return (
    <div className="stack">
      <p style={{ margin: 0 }}>{recommendation.recommendation.summary}</p>
      <dl className="kv">
        <dt>Status</dt>
        <dd>
          <StatusBadge status={approval.status} />
        </dd>
        <dt>Order value</dt>
        <dd>{formatMoney(approval.orderValue)}</dd>
        <dt>Requested by</dt>
        <dd>
          {approval.requestedBy} ({humanize(approval.requesterRole)}), {formatDateTime(approval.createdAt)}
        </dd>
        <dt>Required approvals</dt>
        <dd>
          {approval.requiredRoles.map((role) => (
            <Badge key={role} tone={approval.approvedRoles.includes(role) ? "good" : "warn"}>
              {humanize(role)} {approval.approvedRoles.includes(role) ? "approved" : "needed"}
            </Badge>
          ))}
        </dd>
      </dl>

      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Supplier</th>
              <th>SKU</th>
              <th>Warehouse</th>
              <th className="num">Quantity</th>
              <th className="num">Unit price</th>
            </tr>
          </thead>
          <tbody>
            {recommendation.lines.map((l) => (
              <tr key={l.lineNo}>
                <td>{l.supplierId}</td>
                <td>{l.skuId}</td>
                <td>{l.warehouseId}</td>
                <td className="num">{formatInt(l.quantity)}</td>
                <td className="num">{formatUnitPrice(l.unitPrice)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p>
        <Link href={`/workspace/${encodeURIComponent(approval.recommendationId)}`}>
          Full details
        </Link>
      </p>

      {decisions.length > 0 ? (
        <div>
          <h3>Decisions so far</h3>
          <ul>
            {decisions.map((d) => (
              <li key={d.decisionId}>
                {formatDateTime(d.decidedAt)}: {d.decidedBy} ({humanize(d.approverRole)}){" "}
                {d.outcome.toLowerCase()}
                {d.rationale ? ` — ${d.rationale}` : ""}
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {approval.status === "PENDING" ? (
        <div>
          <h3>Your decision</h3>
          <ApprovalActions approvalId={approval.approvalId} onDecided={onDecided} />
        </div>
      ) : (
        <Notice tone="info">
          This approval is {approval.status.toLowerCase()}.
          {approval.status === "APPROVED"
            ? " Approved purchase orders were created; placing them with suppliers happens outside this system."
            : " No purchase order was created."}
        </Notice>
      )}
    </div>
  );
}

function Detail({ id, onChanged }: { id: string; onChanged: () => void }) {
  const { user, ready } = useSession();
  const { state, reload } = useResource(ready ? `${user.userId}:${id}` : null, (signal) =>
    getApproval(id, signal),
  );
  return (
    <ResourceView state={state} onRetry={reload} loadingLabel="Loading approval…">
      {(detail) => (
        <ApprovalBody
          detail={detail}
          onDecided={() => {
            reload();
            onChanged();
          }}
        />
      )}
    </ResourceView>
  );
}

export function Approvals() {
  const { user, ready } = useSession();
  const params = useSearchParams();
  const [status, setStatus] = useState<ApprovalStatus | "ALL">("PENDING");
  const [chosen, setChosen] = useState<string | null>(params.get("open"));
  const { state, reload } = useResource(ready ? `${user.userId}:${status}` : null, (signal) =>
    listApprovals(status === "ALL" ? undefined : status, signal),
  );

  return (
    <div className="stack">
      <div>
        <h1>Approvals</h1>
        <p className="lede">No order is placed until the right people approve it.</p>
      </div>
      <div className="grid-2" style={{ gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1.4fr)" }}>
        <Panel
          title="Requests"
          id="queue"
          actions={
            <label className="row">
              <span className="muted">Show</span>
              <select value={status} onChange={(e) => setStatus(e.target.value as ApprovalStatus | "ALL")}>
                <option value="PENDING">Pending</option>
                <option value="APPROVED">Approved</option>
                <option value="REJECTED">Rejected</option>
                <option value="ALL">All</option>
              </select>
            </label>
          }
        >
          <ResourceView state={state} onRetry={reload}>
            {(rows) =>
              rows.length === 0 ? (
                <EmptyState>Nothing to show.</EmptyState>
              ) : (
                <div className="table-scroll">
                  <table>
                    <thead>
                      <tr>
                        <th>Approval</th>
                        <th className="num">Value</th>
                        <th>Status</th>
                        <th>Waiting for</th>
                      </tr>
                    </thead>
                    <tbody>
                      {rows.map((a) => (
                        <tr key={a.approvalId} className={a.approvalId === chosen ? "row-selected" : undefined}>
                          <td>
                            <button
                              type="button"
                              className="link-button"
                              aria-current={a.approvalId === chosen ? "true" : undefined}
                              onClick={() => setChosen(a.approvalId)}
                            >
                              {a.approvalId}
                            </button>
                          </td>
                          <td className="num">{formatMoney(a.orderValue)}</td>
                          <td>
                            <StatusBadge status={a.status} />
                          </td>
                          <td>
                            {a.status === "PENDING"
                              ? a.requiredRoles
                                  .filter((r) => !a.approvedRoles.includes(r))
                                  .map(humanize)
                                  .join(", ")
                              : "—"}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )
            }
          </ResourceView>
        </Panel>
        <Panel title={chosen ? `Approval ${chosen}` : "Approval"} id="approval-detail">
          {chosen ? (
            <Detail key={chosen} id={chosen} onChanged={reload} />
          ) : (
            <EmptyState>Pick a request from the list.</EmptyState>
          )}
        </Panel>
      </div>
    </div>
  );
}
