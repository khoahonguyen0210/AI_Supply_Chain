"use client";

import Link from "next/link";
import { EmptyState, Panel, ResourceView, StatusBadge } from "@/components/ui";
import { listRecommendations, listScenarios } from "@/lib/api/decisions";
import { formatDate, formatMoney, formatPercent, humanize } from "@/lib/format";
import { useSession } from "@/lib/session";
import { useResource } from "@/lib/useResource";

export function RecommendationsPanel() {
  const { user, ready } = useSession();
  const { state, reload } = useResource(ready ? user.userId : null, (signal) =>
    listRecommendations(undefined, signal),
  );
  return (
    <Panel
      title="Recommendations"
      id="recommendations"
      actions={<Link href="/copilot">Ask the copilot</Link>}
    >
      <ResourceView state={state} onRetry={reload}>
        {(rows) =>
          rows.length === 0 ? (
            <EmptyState>
              No recommendations yet. Ask the copilot what to do about a demand change and it will
              prepare one for approval.
            </EmptyState>
          ) : (
            <div className="table-scroll">
              <table>
                <thead>
                  <tr>
                    <th>Recommendation</th>
                    <th>Status</th>
                    <th className="num">Objective</th>
                    <th className="num">Expected service</th>
                    <th>Horizon</th>
                  </tr>
                </thead>
                <tbody>
                  {rows.slice(0, 8).map((r) => (
                    <tr key={r.recommendationId}>
                      <td>
                        <Link href={`/workspace/${encodeURIComponent(r.recommendationId)}`}>
                          {r.summary}
                        </Link>
                      </td>
                      <td>
                        <StatusBadge status={r.status} />
                      </td>
                      <td className="num">{formatMoney(r.objectiveValue)}</td>
                      <td className="num">{formatPercent(r.expectedServiceLevel)}</td>
                      <td>
                        {formatDate(r.horizonStart)} to {formatDate(r.horizonEnd)}
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
  );
}

export function ScenariosPanel() {
  const { user, ready } = useSession();
  const { state, reload } = useResource(ready ? user.userId : null, (signal) =>
    listScenarios(signal),
  );
  return (
    <Panel title="Scenarios" id="scenarios" actions={<Link href="/workspace">Open workspace</Link>}>
      <ResourceView state={state} onRetry={reload}>
        {(rows) =>
          rows.length === 0 ? (
            <EmptyState>
              No saved scenarios. Define a disruption in the decision workspace to stress a plan.
            </EmptyState>
          ) : (
            <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
              {rows.slice(0, 8).map((s) => (
                <li key={s.scenarioId}>
                  <strong>{s.name}</strong> <span className="muted">{humanize(s.scenarioType)}</span>
                  <div className="muted">
                    {Object.entries(s.parameters)
                      .map(([k, v]) => `${k}: ${v}`)
                      .join(", ") || "no parameters"}
                  </div>
                </li>
              ))}
            </ul>
          )
        }
      </ResourceView>
    </Panel>
  );
}
