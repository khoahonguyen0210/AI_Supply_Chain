import { screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { errorResponse, renderWithSession, stubBackend } from "@/test/render";
import type { AiTelemetry, OpsSummary } from "@/lib/api/types";
import { Operations } from "./Operations";

const SUMMARY: OpsSummary = {
  api: {
    requests: 1200,
    serverErrors: 6,
    clientErrors: 30,
    errorRate: 0.005,
    p50Millis: 12.4,
    p95Millis: 88.1,
    requestsPerSecond: 3.5,
    uptimeSeconds: 343,
  },
  queue: {
    byStatus: { QUEUED: 4, RUNNING: 1, SUCCEEDED: 90, FAILED: 2 },
    oldestQueuedSeconds: 7.2,
    workerUtilization: 0.31,
    meanDurationMillis: { FORECAST: 40, OPTIMIZATION: 2100, SCENARIO: 5200, BATCH_EVALUATION: 0 },
    failedAttempts: { FORECAST: 0, OPTIMIZATION: 2, SCENARIO: 0, BATCH_EVALUATION: 0 },
  },
};

const series = { count: 10, failures: 1, failureRate: 0.1, meanMillis: 20, p50Millis: 15, p95Millis: 60 };

const AI: AiTelemetry = {
  runtime: {
    uptimeSeconds: 100,
    forecast: series,
    tools: {
      calls: 40,
      successRate: 0.9,
      byTool: { get_forecast: series },
      errors: { "optimize_procurement:UNKNOWN_SKU": 2 },
    },
    agent: {
      ...series,
      byStatus: { COMPLETED: 6, REFUSED: 2 },
      guardrailFindings: { APPROVAL_BYPASS: 2 },
    },
    retrieval: { ...series, byStatus: { ANSWERED: 3, INSUFFICIENT_EVIDENCE: 1 }, answeredShare: 0.75 },
    models: {
      "claude-opus-5-5": { ...series, inputTokens: 12000, outputTokens: 3000, estimatedCostUsd: null },
    },
    costNote: "cost is not reported: no per-token prices are configured",
  },
  quality: {
    note: "Offline evaluation on fixed datasets and cases; see the experiment artifacts.",
    forecast: {
      available: true,
      modelVersion: "lgbm-test",
      selectedBaseline: "moving_average_13",
      testMaeImprovementVsBaseline: 0.11,
      testMae: 30.1,
      testWape: 0.93,
      intervalNominalLevel: 0.8,
      intervalTestCoverage: 0.875,
      codeRevision: "abc1234",
    },
    rag: {
      available: true,
      cases: 56,
      embedder: "bge",
      generator: "extractive-stub",
      hitAt1: 0.94,
      hitAt3: 1,
      mrr: 0.97,
      answerAccuracy: 0.97,
      citationAccuracy: 1,
      groundedness: 1,
      restrictedLeaks: 0,
      llmGeneratorMetrics: "NOT YET MEASURED",
      codeRevision: "abc1234",
    },
    agent: {
      available: true,
      planner: "rule",
      cases: 40,
      workflowSuccess: 0.825,
      holdoutWorkflowSuccess: 0.222,
      toolCorrectness: 0.87,
      parameterCorrectness: 0.64,
      groundedNumbers: 1,
      permissionCompliance: 1,
      appropriateRefusal: 1,
      llmPlannerMetrics: "NOT YET MEASURED",
      codeRevision: "abc1234",
    },
  },
};

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Operations", () => {
  it("shows API health, queue state and worker utilization", async () => {
    stubBackend({ "/api/ops/summary": SUMMARY, "/api/ops/ai": AI });
    renderWithSession(<Operations />);
    expect(await screen.findByText("1,200")).toBeInTheDocument();
    expect(screen.getByText("0.50%")).toBeInTheDocument();
    expect(screen.getByText("88.1 ms")).toBeInTheDocument();
    expect(screen.getByText("31.0%")).toBeInTheDocument();
    expect(screen.getByText(/oldest waiting 7.2 s/)).toBeInTheDocument();
    expect(screen.getByText("Batch evaluation")).toBeInTheDocument();
  });

  it("shows live AI behaviour including guardrail findings and unpriced model use", async () => {
    stubBackend({ "/api/ops/summary": SUMMARY, "/api/ops/ai": AI });
    renderWithSession(<Operations />);
    expect(await screen.findByText("75.0%")).toBeInTheDocument();
    expect(screen.getByText(/Approval bypass: 2/)).toBeInTheDocument();
    expect(screen.getByText(/Optimize procurement – unknown sku: 2/)).toBeInTheDocument();
    expect(screen.getByText("claude-opus-5-5")).toBeInTheDocument();
    expect(screen.getByText("not priced")).toBeInTheDocument();
    expect(screen.getByText(/no per-token prices are configured/)).toBeInTheDocument();
  });

  it("reports offline results honestly, including what was never measured", async () => {
    stubBackend({ "/api/ops/summary": SUMMARY, "/api/ops/ai": AI });
    renderWithSession(<Operations />);
    expect(await screen.findByText(/Offline evaluation on fixed datasets/)).toBeInTheDocument();
    expect(screen.getAllByText("NOT YET MEASURED")).toHaveLength(2);
    expect(screen.getByText("22.2%")).toBeInTheDocument(); // the held-out agent result, not hidden
    expect(screen.getByText(/87\.5% \(target 80\.0%\)/)).toBeInTheDocument();
  });

  it("tells non-admins they are not allowed instead of showing empty panels", async () => {
    stubBackend({
      "/api/ops/summary": () => errorResponse(403, "FORBIDDEN", "role planner may not do this"),
      "/api/ops/ai": () => errorResponse(403, "FORBIDDEN", "role planner may not do this"),
    });
    renderWithSession(<Operations />);
    expect((await screen.findAllByText("role planner may not do this")).length).toBeGreaterThan(0);
  });

  it("says when an evaluation has not been stored", async () => {
    const quality = {
      ...AI.quality,
      forecast: { available: false as const },
      rag: { available: false as const },
      agent: { available: false as const },
    };
    stubBackend({ "/api/ops/summary": SUMMARY, "/api/ops/ai": { ...AI, quality } });
    renderWithSession(<Operations />);
    expect(await screen.findByText("No forecast evaluation has been stored.")).toBeInTheDocument();
    expect(screen.getByText("No agent evaluation has been stored.")).toBeInTheDocument();
  });
});
