import Link from "next/link";
import { Citations } from "@/components/Citations";
import { Notice, StatusBadge } from "@/components/ui";
import type { AgentTask, TraceStep } from "@/lib/api/types";
import { humanize } from "@/lib/format";

const TOOL_LABELS: Record<string, string> = {
  get_forecast: "Looked up the demand forecast",
  get_inventory: "Checked inventory",
  assess_inventory_need: "Worked out how much stock is needed",
  search_suppliers: "Compared suppliers",
  get_supplier_performance: "Checked supplier performance",
  search_policies: "Searched contracts and policies",
  optimize_procurement: "Worked out the cheapest purchase plan",
  plan_fulfillment: "Planned which warehouse ships where",
  run_scenario: "Tested what could go wrong",
  prepare_purchase_order: "Requested approval for the order",
};

export function stepLabel(step: TraceStep): string {
  if (step.kind === "TOOL_CALL" && step.tool) return TOOL_LABELS[step.tool] ?? humanize(step.tool);
  if (step.kind === "REFUSAL") return "Declined the request";
  if (step.kind === "CLARIFICATION") return "Asked for clarification";
  return "Wrote the answer";
}

const GUARDRAIL_TEXT: Record<string, string> = {
  APPROVAL_BYPASS: "A request to skip approval was blocked.",
  SELF_APPROVAL: "A request for the assistant to approve an order was blocked.",
  RULE_OVERRIDE: "A request to ignore the rules was blocked.",
  PROMPT_EXTRACTION: "A request for internal instructions was blocked.",
  NOT_AUTHORIZED: "A tool was refused because your role may not use it.",
  INVALID_ARGUMENTS: "A tool call with invalid arguments was rejected.",
  INVALID_RESULT: "A tool result failed its sanity check and was not used.",
  UNKNOWN_TOOL: "The assistant asked for a tool that does not exist.",
  REPEATED_CALL: "The assistant repeated a call and was stopped.",
  PLANNER_FAILURE: "The planner failed; no action was taken.",
  MAX_STEPS: "The task needed more steps than allowed.",
};

export function guardrailText(violation: string): string {
  const code = violation.split(":")[0];
  if (code === "UNSUPPORTED_NUMBERS") {
    return "An answer was held back because it contained numbers that no tool had reported.";
  }
  return GUARDRAIL_TEXT[code] ?? humanize(code);
}

/** The steps the assistant took, one line each; arguments and detail are one click away. */
export function ActionTrace({ steps }: { steps: TraceStep[] }) {
  const actions = steps.filter((s) => s.kind === "TOOL_CALL");
  if (actions.length === 0) return null;
  return (
    <details>
      <summary>How this was worked out ({actions.length} steps)</summary>
      <ol className="trace">
        {actions.map((step) => (
          <li key={step.index} className={step.ok ? undefined : "trace-failed"}>
            <strong>{stepLabel(step)}</strong>
            {step.replan ? <span className="muted"> · re-planned after a result</span> : null}
            {!step.ok ? <span> · failed ({step.errorCode})</span> : null}
            {step.reason ? <div className="muted">{step.reason}</div> : null}
            <details>
              <summary>Details</summary>
              <div>
                <code>{step.tool}</code> {JSON.stringify(step.arguments)}
              </div>
              <div className="muted">{step.summary}</div>
            </details>
          </li>
        ))}
      </ol>
    </details>
  );
}

/** Long answers show the first line and conclusion; the rest folds away. */
function AnswerText({ answer }: { answer: string }) {
  const lines = answer.split("\n").filter((line) => line.trim() !== "");
  if (lines.length <= 3) return <div>{answer}</div>;
  const middle = lines.slice(1, -1);
  return (
    <div>
      <div>{lines[0]}</div>
      <div style={{ marginTop: 6 }}>{lines[lines.length - 1]}</div>
      <details style={{ marginTop: 8 }}>
        <summary>Show the full answer</summary>
        <div className="stack" style={{ gap: 6, marginTop: 6 }}>
          {middle.map((line, i) => (
            <div key={i}>{line}</div>
          ))}
        </div>
      </details>
    </div>
  );
}

/** One request and the assistant's answer, with its status, assumptions, evidence, trace and next step. */
export function TaskCard({ task }: { task: AgentTask }) {
  return (
    <article className="chat" aria-label={`Request: ${task.requestText}`}>
      <div className="bubble bubble-user">{task.requestText}</div>
      <div className="bubble">
        <div className="row" style={{ marginBottom: 6 }}>
          <StatusBadge status={task.status} />
        </div>
        <AnswerText answer={task.answer} />

        {task.assumptions.length > 0 ? (
          <>
            <h3>Assumptions</h3>
            <ul style={{ margin: 0 }}>
              {task.assumptions.map((a) => (
                <li key={a}>{a}</li>
              ))}
            </ul>
          </>
        ) : null}

        {task.citations.length > 0 ? (
          <>
            <h3>Sources</h3>
            <Citations citations={task.citations} />
          </>
        ) : null}

        {task.recommendationId ? (
          <p>
            <Link href={`/workspace/${encodeURIComponent(task.recommendationId)}`}>
              Open recommendation {task.recommendationId}
            </Link>
            {task.approvalId ? (
              <>
                {" · "}
                <Link href={`/approvals?open=${encodeURIComponent(task.approvalId)}`}>
                  Review approval {task.approvalId}
                </Link>
              </>
            ) : null}
          </p>
        ) : null}

        {task.status === "AWAITING_APPROVAL" ? (
          <Notice tone="warn">Nothing has been ordered yet. This needs approval first.</Notice>
        ) : null}

        {task.violations.length > 0 ? (
          <Notice tone="info">
            Guardrails: {[...new Set(task.violations.map(guardrailText))].join(" ")}
          </Notice>
        ) : null}

        <ActionTrace steps={task.trace} />
      </div>
    </article>
  );
}
