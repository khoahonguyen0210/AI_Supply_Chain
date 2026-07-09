"use client";

import { useEffect, useState } from "react";
import { ApiError } from "@/lib/api/client";
import { getHealth } from "@/lib/api/health";
import type { HealthResponse } from "@/lib/api/types";

type State =
  | { phase: "loading" }
  | { phase: "ok"; health: HealthResponse }
  | { phase: "error"; message: string };

export function ConnectionStatus() {
  const [state, setState] = useState<State>({ phase: "loading" });

  useEffect(() => {
    const controller = new AbortController();
    getHealth(controller.signal)
      .then((health) => setState({ phase: "ok", health }))
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        const message = error instanceof ApiError ? error.message : "Unexpected error";
        setState({ phase: "error", message });
      });
    return () => controller.abort();
  }, []);

  if (state.phase === "loading") return <p role="status">Checking backend…</p>;
  if (state.phase === "error") {
    return (
      <p role="alert" className="status-error">
        Backend check failed: {state.message}
      </p>
    );
  }
  return (
    <dl className="status-ok" aria-label="Backend health">
      <dt>Status</dt>
      <dd>{state.health.status}</dd>
      <dt>Service</dt>
      <dd>{state.health.service}</dd>
      <dt>Version</dt>
      <dd>{state.health.version}</dd>
      <dt>Server time</dt>
      <dd>{state.health.timestamp}</dd>
    </dl>
  );
}
