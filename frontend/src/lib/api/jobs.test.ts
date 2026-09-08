import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { runJob, waitForJob } from "./jobs";

const fetchMock = vi.fn();

function job(status: string, extra: Record<string, unknown> = {}): Response {
  return new Response(
    JSON.stringify({
      id: "job-1",
      type: "OPTIMIZATION",
      status,
      attempts: 1,
      maxAttempts: 3,
      result: null,
      errorCode: null,
      errorMessage: null,
      lastError: null,
      createdAt: "t",
      startedAt: null,
      finishedAt: null,
      ...extra,
    }),
    { status: 200, headers: { "Content-Type": "application/json" } },
  );
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
  fetchMock.mockReset();
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("waitForJob", () => {
  it("polls until the job succeeds and returns its result", async () => {
    fetchMock
      .mockResolvedValueOnce(job("QUEUED"))
      .mockResolvedValueOnce(job("RUNNING"))
      .mockResolvedValueOnce(job("SUCCEEDED", { result: { planId: "PLAN-1" } }));
    const seen: string[] = [];
    const result = await waitForJob<{ planId: string }>("job-1", {
      intervalMs: 1,
      onUpdate: (j) => seen.push(j.status),
    });
    expect(result.planId).toBe("PLAN-1");
    expect(seen).toEqual(["QUEUED", "RUNNING", "SUCCEEDED"]);
  });

  it("raises the job's own error code when it fails", async () => {
    fetchMock.mockResolvedValueOnce(
      job("FAILED", { errorCode: "UNKNOWN_SKU", errorMessage: "unknown SKU NOPE" }),
    );
    await expect(waitForJob("job-1", { intervalMs: 1 })).rejects.toMatchObject({
      code: "UNKNOWN_SKU",
      message: "unknown SKU NOPE",
    });
  });

  it("gives up after the timeout", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(job("RUNNING")));
    await expect(waitForJob("job-1", { intervalMs: 1, timeoutMs: 20 })).rejects.toMatchObject({
      code: "JOB_TIMEOUT",
    });
  });

  it("stops polling when aborted", async () => {
    fetchMock.mockImplementation(() => Promise.resolve(job("RUNNING")));
    const controller = new AbortController();
    const waiting = waitForJob("job-1", { intervalMs: 50, signal: controller.signal });
    setTimeout(() => controller.abort(), 10);
    await expect(waiting).rejects.toMatchObject({ name: "AbortError" });
  });
});

describe("runJob", () => {
  it("submits with the idempotency key and returns the result", async () => {
    fetchMock
      .mockResolvedValueOnce(job("QUEUED"))
      .mockResolvedValueOnce(job("SUCCEEDED", { result: { ok: true } }));
    const result = await runJob<{ ok: boolean }>(
      "OPTIMIZATION",
      { skuIds: ["S"] },
      { idempotencyKey: "k", intervalMs: 1 },
    );
    expect(result.ok).toBe(true);
    const [url, init] = fetchMock.mock.calls[0];
    expect(url).toBe("/api/jobs");
    expect(init.headers["Idempotency-Key"]).toBe("k");
    expect(JSON.parse(init.body as string)).toEqual({
      type: "OPTIMIZATION",
      payload: { skuIds: ["S"] },
    });
  });
});
