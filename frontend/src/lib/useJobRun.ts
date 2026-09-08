"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { errorMessage, isAbort } from "./api/client";
import { runJob } from "./api/jobs";
import type { Job, JobType } from "./api/types";

export type JobRun<R> =
  | { phase: "idle" }
  | { phase: "running"; job: Job | null }
  | { phase: "done"; result: R }
  | { phase: "error"; message: string; code?: string };

/**
 * Runs one long job at a time: submit, poll, expose progress and the result. A new run aborts the previous
 * poll and leaving the page stops polling. Each run gets a fresh idempotency key, so a transport retry of
 * the same submission cannot queue the work twice.
 */
export function useJobRun<R>(): {
  state: JobRun<R>;
  run: (type: JobType, payload: unknown, idempotencyKey?: string) => Promise<R | undefined>;
  reset: () => void;
} {
  const [state, setState] = useState<JobRun<R>>({ phase: "idle" });
  const controller = useRef<AbortController | null>(null);

  useEffect(() => () => controller.current?.abort(), []);

  const run = useCallback(async (type: JobType, payload: unknown, idempotencyKey?: string) => {
    controller.current?.abort();
    const abort = new AbortController();
    controller.current = abort;
    setState({ phase: "running", job: null });
    try {
      const result = await runJob<R>(type, payload, {
        signal: abort.signal,
        idempotencyKey: idempotencyKey ?? crypto.randomUUID(),
        onUpdate: (job) => setState({ phase: "running", job }),
      });
      setState({ phase: "done", result });
      return result;
    } catch (error) {
      if (isAbort(error)) return undefined;
      const code = (error as { code?: string }).code;
      setState({ phase: "error", message: errorMessage(error), code });
      return undefined;
    }
  }, []);

  const reset = useCallback(() => {
    controller.current?.abort();
    setState({ phase: "idle" });
  }, []);

  return { state, run, reset };
}

export function jobProgressLabel(job: Job | null): string {
  if (!job) return "Submitting…";
  if (job.status === "QUEUED") {
    return job.lastError ? `Queued for retry (attempt ${job.attempts} of ${job.maxAttempts})…` : "Queued…";
  }
  return `Running (attempt ${job.attempts} of ${job.maxAttempts})…`;
}
