import { ApiError, apiGet, apiPost } from "./client";
import type { Job, JobType } from "./types";

export const submitJob = (
  type: JobType,
  payload: unknown,
  idempotencyKey?: string,
): Promise<Job> => apiPost<Job>("/api/jobs", { type, payload }, { idempotencyKey });

export const getJob = <R = unknown>(id: string, signal?: AbortSignal) =>
  apiGet<Job<R>>(`/api/jobs/${encodeURIComponent(id)}`, signal);

export interface PollOptions {
  signal?: AbortSignal;
  intervalMs?: number;
  timeoutMs?: number;
  onUpdate?: (job: Job) => void;
}

const sleep = (ms: number, signal?: AbortSignal) =>
  new Promise<void>((resolve, reject) => {
    const timer = setTimeout(resolve, ms);
    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(new DOMException("Aborted", "AbortError"));
      },
      { once: true },
    );
  });

export async function waitForJob<R>(jobId: string, options: PollOptions = {}): Promise<R> {
  const { signal, intervalMs = 1000, timeoutMs = 5 * 60_000, onUpdate } = options;
  const deadline = Date.now() + timeoutMs;
  for (;;) {
    const job = await getJob<R>(jobId, signal);
    onUpdate?.(job);
    if (job.status === "SUCCEEDED") return job.result as R;
    if (job.status === "FAILED") {
      throw new ApiError(job.errorMessage ?? "Job failed", 422, job.errorCode ?? "JOB_FAILED");
    }
    if (Date.now() >= deadline) {
      throw new ApiError("The job is taking longer than expected", 0, "JOB_TIMEOUT");
    }
    await sleep(intervalMs, signal);
  }
}

export async function runJob<R>(
  type: JobType,
  payload: unknown,
  options: PollOptions & { idempotencyKey?: string } = {},
): Promise<R> {
  const job = await submitJob(type, payload, options.idempotencyKey);
  options.onUpdate?.(job);
  return waitForJob<R>(job.id, options);
}
