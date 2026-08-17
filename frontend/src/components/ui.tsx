import type { ReactNode } from "react";
import type { Resource } from "@/lib/useResource";

export function Panel({
  title,
  actions,
  children,
  id,
}: {
  title: string;
  actions?: ReactNode;
  children: ReactNode;
  id?: string;
}) {
  const headingId = id ? `${id}-heading` : undefined;
  return (
    <section className="panel" aria-labelledby={headingId} id={id}>
      <header className="panel-header">
        <h2 id={headingId}>{title}</h2>
        {actions ? <div className="panel-actions">{actions}</div> : null}
      </header>
      {children}
    </section>
  );
}

export type Tone = "neutral" | "good" | "warn" | "bad" | "info";

export function Badge({ tone = "neutral", children }: { tone?: Tone; children: ReactNode }) {
  return <span className={`badge badge-${tone}`}>{children}</span>;
}

const STATUS_TONES: Record<string, Tone> = {
  APPROVED: "good",
  COMPLETED: "good",
  SUCCEEDED: "good",
  PENDING: "warn",
  PENDING_APPROVAL: "warn",
  AWAITING_APPROVAL: "warn",
  QUEUED: "info",
  RUNNING: "info",
  PROPOSED: "info",
  NEEDS_CLARIFICATION: "info",
  REJECTED: "bad",
  REFUSED: "bad",
  FAILED: "bad",
};

export function StatusBadge({ status }: { status: string }) {
  return <Badge tone={STATUS_TONES[status] ?? "neutral"}>{status.replace(/_/g, " ")}</Badge>;
}

export function Notice({
  tone = "info",
  children,
}: {
  tone?: "info" | "warn" | "bad";
  children: ReactNode;
}) {
  return (
    <p className={`notice notice-${tone}`} role={tone === "bad" ? "alert" : "status"}>
      {children}
    </p>
  );
}

export function ResourceView<T>({
  state,
  onRetry,
  children,
  loadingLabel = "Loading…",
}: {
  state: Resource<T>;
  onRetry?: () => void;
  children: (data: T) => ReactNode;
  loadingLabel?: string;
}) {
  if (state.phase === "loading") return <p role="status">{loadingLabel}</p>;
  if (state.phase === "error") {
    return (
      <p className="notice notice-bad" role="alert">
        {state.message}
        {onRetry ? (
          <>
            {" "}
            <button type="button" className="link-button" onClick={onRetry}>
              Retry
            </button>
          </>
        ) : null}
      </p>
    );
  }
  return <>{children(state.data)}</>;
}

export function Stat({
  label,
  value,
  hint,
}: {
  label: string;
  value: ReactNode;
  hint?: ReactNode;
}) {
  return (
    <div className="stat">
      <dt>{label}</dt>
      <dd>{value}</dd>
      {hint ? <small>{hint}</small> : null}
    </div>
  );
}

export function EmptyState({ children }: { children: ReactNode }) {
  return <p className="muted">{children}</p>;
}
