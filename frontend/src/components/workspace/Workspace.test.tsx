import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { errorResponse, renderWithSession, stubBackend } from "@/test/render";
import type { PlanResult, ScenarioRunResult } from "@/lib/api/types";
import { RecommendationBody } from "./RecommendationDetailView";
import { Workspace } from "./Workspace";

const PLAN: PlanResult = {
  planId: "PLAN-1",
  skuIds: ["SKU-001"],
  horizonWeeks: 4,
  demandMultiplier: 1.2,
  serviceLevelTarget: 0.95,
  budget: null,
  solverStatus: "OPTIMAL",
  objective: 18250,
  spend: 16000,
  orderValue: 15800,
  totalDemand: 1200,
  fillRate: 0.985,
  unmetDemand: 18,
  orders: 2,
  unitsOrdered: 1100,
  customerFillRate: 0.97,
  violations: [],
  bySupplier: [{ supplierId: "SUP-1", units: 1100, spend: 15800 }],
  lines: [
    { supplierId: "SUP-1", skuId: "SKU-001", warehouseId: "W1", quantity: 1100, unitPrice: 14.36, value: 15800 },
  ],
  bindingConstraints: [{ kind: "SUPPLIER_CAPACITY", subject: "SUP-1", utilization: 0.92 }],
};

const SCENARIO_RESULT: ScenarioRunResult = {
  plan: PLAN,
  scenario: {
    planId: "PLAN-1",
    scenarioType: "SUPPLIER_OUTAGE",
    parameters: { supplier_id: "SUP-1" },
    assumptionsChanged: ["supplier SUP-1 offers (SUP-1): 3.0 -> 0.0"],
    baselineObjective: 18250,
    disruptedObjectiveDelta: 9400,
    responseObjectiveDelta: 2100,
    resilienceCost: 2100,
    responseBenefit: 7300,
    serviceDeltaDisrupted: -0.21,
    serviceDeltaResponse: -0.02,
    baselineCustomerFillRate: 0.97,
    responseCustomerFillRate: 0.95,
    newlyBinding: ["SUPPLIER_CAPACITY SUP-2"],
    changedPurchaseLines: 1,
    supplierShifts: [{ supplierId: "SUP-2", baselineUnits: 0, responseUnits: 1100 }],
  },
};

function job(id: string, status: string, result: unknown = null, extra: Record<string, unknown> = {}) {
  return {
    id,
    type: "OPTIMIZATION",
    status,
    attempts: 1,
    maxAttempts: 3,
    result,
    errorCode: null,
    errorMessage: null,
    lastError: null,
    createdAt: "t",
    startedAt: null,
    finishedAt: null,
    ...extra,
  };
}

const SEARCH = {
  skuId: "SKU-001",
  warehouseId: "W1",
  quantity: 1100,
  maxLeadTimeDays: 28,
  eligibleCount: 2,
  ranked: [
    {
      rank: 1,
      supplierId: "SUP-1",
      supplierName: "Acme",
      landedUnitCost: 14.8,
      totalCost: 16280,
      costVsCheapestPct: 0,
      leadTimeDays: 7,
      reliability: 0.95,
      qualityScore: 0.9,
    },
    {
      rank: 2,
      supplierId: "SUP-2",
      supplierName: "Budget Co",
      landedUnitCost: 15.9,
      totalCost: 17490,
      costVsCheapestPct: 7.4,
      leadTimeDays: 14,
      reliability: 0.8,
      qualityScore: 0.8,
    },
  ],
  rejected: {},
  cheapestOverall: null,
  tradeOffs: [],
};

beforeEach(() => {
  stubBackend({
    "/api/skus": [
      { skuId: "SKU-001", name: "Widget", category: "home", unitPrice: 20, unitVolume: 0.1, requiredCertifications: [] },
      { skuId: "SKU-002", name: "Gadget", category: "home", unitPrice: 35, unitVolume: 0.2, requiredCertifications: [] },
    ],
    "/api/jobs": (url: string, init: RequestInit) => {
      if (init.method === "POST") {
        const body = JSON.parse(init.body as string) as { type: string };
        return new Response(JSON.stringify(job(`job-${body.type}`, "QUEUED")), { status: 202 });
      }
      return url.endsWith("job-OPTIMIZATION")
        ? job("job-OPTIMIZATION", "SUCCEEDED", PLAN)
        : job("job-SCENARIO", "SUCCEEDED", SCENARIO_RESULT, { type: "SCENARIO" });
    },
    "/api/suppliers/search": SEARCH,
    "/api/scenarios": (url: string) =>
      url.endsWith("/runs")
        ? new Response(JSON.stringify(job("job-SCENARIO", "QUEUED", null, { type: "SCENARIO" })), { status: 202 })
        : new Response(
            JSON.stringify({
              scenarioId: "SCN-1",
              name: "Outage",
              scenarioType: "SUPPLIER_OUTAGE",
              parameters: { supplier_id: "SUP-1" },
              createdAt: "t",
            }),
            { status: 201 },
          ),
    "/api/documents/ask": {
      question: "q",
      status: "ANSWERED",
      answer: "Orders above USD 15,000 need procurement manager approval [S1].",
      citations: [
        { documentId: "POL-APPROVAL", version: "v2", status: "CURRENT", excerpt: "above USD 15,000 require procurement manager approval" },
      ],
    },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

async function optimize() {
  await userEvent.click(await screen.findByLabelText("SKU-001"));
  await userEvent.click(screen.getByRole("button", { name: "Optimize plan" }));
}

describe("Decision workspace", () => {
  it("needs a product before it will optimize", async () => {
    renderWithSession(<Workspace />);
    await screen.findByLabelText("SKU-001");
    expect(screen.getByRole("button", { name: "Optimize plan" })).toBeDisabled();
  });

  it("runs the optimizer as a job and shows assumptions, lines and binding constraints", async () => {
    renderWithSession(<Workspace />);
    await optimize();

    expect(await screen.findByText("All constraints satisfied")).toBeInTheDocument();
    const plan = screen.getByRole("heading", { name: "Purchase plan" }).closest("section")!;
    expect(within(plan).getByText("forecast × 1.2")).toBeInTheDocument();
    expect(within(plan).getByText("OPTIMAL")).toBeInTheDocument();
    expect(within(plan).getByText("$18,250")).toBeInTheDocument();
    expect(within(plan).getByText(/Supplier capacity SUP-1: 92% used/)).toBeInTheDocument();
    expect(within(plan).getByText("$15,800", { selector: "td" })).toBeInTheDocument();
  });

  it("submits the plan the planner described", async () => {
    const { calls } = stubBackendCalls();
    renderWithSession(<Workspace />);
    await userEvent.click(await screen.findByLabelText("SKU-001"));
    await userEvent.clear(screen.getByLabelText("Demand adjustment (×)"));
    await userEvent.type(screen.getByLabelText("Demand adjustment (×)"), "1.2");
    await userEvent.type(screen.getByLabelText("Budget (USD, optional)"), "20000");
    await userEvent.click(screen.getByRole("button", { name: "Optimize plan" }));
    await screen.findByText("All constraints satisfied");

    const submit = calls().find((c) => c.url === "/api/jobs" && c.init.method === "POST")!;
    expect(JSON.parse(submit.init.body as string)).toEqual({
      type: "OPTIMIZATION",
      payload: {
        skuIds: ["SKU-001"],
        horizonWeeks: 4,
        demandMultiplier: 1.2,
        serviceLevel: 0.95,
        budget: 20000,
      },
    });
    expect((submit.init.headers as Record<string, string>)["Idempotency-Key"]).toBeTruthy();
  });

  it("shows why a job failed using the engine's message", async () => {
    stubBackend({
      "/api/skus": [{ skuId: "SKU-001", name: "W", category: "c", unitPrice: 1, unitVolume: 1, requiredCertifications: [] }],
      "/api/jobs": (_url: string, init: RequestInit) =>
        init.method === "POST"
          ? new Response(JSON.stringify(job("j", "QUEUED")), { status: 202 })
          : job("j", "FAILED", null, { errorCode: "INFEASIBLE", errorMessage: "No plan satisfies the budget" }),
    });
    renderWithSession(<Workspace />);
    await optimize();
    expect(await screen.findByText("No plan satisfies the budget")).toBeInTheDocument();
  });

  it("lists the other suppliers for a purchase line", async () => {
    renderWithSession(<Workspace />);
    await optimize();
    await userEvent.click(await screen.findByRole("button", { name: "Alternatives for SKU-001 at W1" }));

    const panel = (await screen.findByRole("heading", { name: "Alternatives for SKU-001 at W1" })).closest(
      "section",
    )!;
    expect(await within(panel).findByText("Budget Co")).toBeInTheDocument();
    expect(within(panel).getByText("+7.4%")).toBeInTheDocument();
    await userEvent.click(within(panel).getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("heading", { name: /Alternatives for/ })).not.toBeInTheDocument();
  });

  it("stress-tests the optimized plan and shows what the disruption does", async () => {
    renderWithSession(<Workspace />);
    expect(screen.getByText(/Optimize a plan first/)).toBeInTheDocument();
    await optimize();
    await screen.findByText("All constraints satisfied");

    await userEvent.selectOptions(screen.getByLabelText("Disruption"), "SUPPLIER_OUTAGE");
    await userEvent.type(screen.getByLabelText("Supplier"), "SUP-1");
    await userEvent.click(screen.getByRole("button", { name: "Run scenario" }));

    expect(await screen.findByText(/supplier SUP-1 offers \(SUP-1\): 3.0 -> 0.0/)).toBeInTheDocument();
    expect(screen.getByText("+$9,400")).toBeInTheDocument();
    expect(screen.getByText("-21.0 pts")).toBeInTheDocument();
    expect(screen.getByText(/Constraints that become binding: SUPPLIER_CAPACITY SUP-2/)).toBeInTheDocument();
  });

  it("will not run a scenario with a missing required field", async () => {
    renderWithSession(<Workspace />);
    await optimize();
    await screen.findByText("All constraints satisfied");
    await userEvent.selectOptions(screen.getByLabelText("Disruption"), "SUPPLIER_OUTAGE");
    expect(screen.getByRole("button", { name: "Run scenario" })).toBeDisabled();
    expect(screen.getByText("Supplier is required")).toBeInTheDocument();
  });

  it("answers a policy question with its citations", async () => {
    renderWithSession(<Workspace />);
    await userEvent.type(await screen.findByLabelText("Question"), "Who approves big orders?");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    expect(await screen.findByText(/need procurement manager approval \[S1\]/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "POL-APPROVAL · v2" })).toHaveAttribute(
      "href",
      "/documents?open=POL-APPROVAL&version=v2",
    );
  });

  it("reports a failed policy question", async () => {
    stubBackend({
      "/api/skus": [],
      "/api/documents/ask": () => errorResponse(502, "ML_SERVICE_UNAVAILABLE", "ML service is unreachable"),
    });
    renderWithSession(<Workspace />);
    await userEvent.type(screen.getByLabelText("Question"), "anything at all");
    await userEvent.click(screen.getByRole("button", { name: "Ask" }));
    await waitFor(() => expect(screen.getByText("ML service is unreachable")).toBeInTheDocument());
  });
});

describe("RecommendationBody", () => {
  const detail = {
    recommendation: {
      recommendationId: "REC-1",
      createdAt: "2024-12-30T08:00:00Z",
      summary: "Buy 1100 widgets from Acme",
      objectiveValue: 18250,
      expectedServiceLevel: 0.97,
      assumptions: ["demand x1.2", "4-week horizon"],
      citations: [{ documentId: "POL-APPROVAL", version: "v2", excerpt: "needs manager approval" }],
      horizonStart: "2024-12-30",
      horizonEnd: "2025-01-27",
      status: "PENDING_APPROVAL" as const,
    },
    lines: [
      { lineNo: 1, supplierId: "SUP-1", skuId: "SKU-001", warehouseId: "W1", quantity: 1100, unitPrice: 14.36, shippingCost: 440 },
    ],
    approval: {
      approvalId: "APR-1",
      recommendationId: "REC-1",
      requestedBy: "pat",
      requesterRole: "planner",
      requiredRoles: ["procurement_manager", "finance"],
      approvedRoles: ["procurement_manager"],
      approvers: ["mia"],
      orderValue: 79000,
      status: "PENDING" as const,
      createdAt: "2024-12-30T08:00:00Z",
      updatedAt: "2024-12-30T09:00:00Z",
    },
    decisions: [
      {
        decisionId: "APR-1-D001",
        decidedBy: "mia",
        approverRole: "procurement_manager",
        outcome: "APPROVED" as const,
        decidedAt: "2024-12-30T09:00:00Z",
        rationale: "within budget",
      },
    ],
  };

  it("shows assumptions, evidence, lines and how far the approval has got", () => {
    renderWithSession(<RecommendationBody detail={detail} />);
    expect(screen.getByText("demand x1.2")).toBeInTheDocument();
    expect(screen.getByText("needs manager approval")).toBeInTheDocument();
    expect(screen.getByText("Procurement manager approved")).toBeInTheDocument();
    expect(screen.getByText("Finance needed")).toBeInTheDocument();
    expect(screen.getByText(/mia \(Procurement manager\) approved — within budget/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open in approvals" })).toHaveAttribute(
      "href",
      "/approvals?open=APR-1",
    );
  });

  it("says when no approval was requested", () => {
    renderWithSession(<RecommendationBody detail={{ ...detail, approval: null, decisions: [] }} />);
    expect(screen.getByText(/No approval has been requested/)).toBeInTheDocument();
  });
});

function stubBackendCalls() {
  const current = (globalThis.fetch as unknown as { mock: { calls: [string, RequestInit][] } }).mock.calls;
  return { calls: () => current.map(([url, init]) => ({ url: String(url), init })) };
}
