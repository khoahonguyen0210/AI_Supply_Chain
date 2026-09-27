import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { errorResponse, renderWithSession, stubBackend } from "@/test/render";
import type { AgentTask } from "@/lib/api/types";
import { Copilot } from "./Copilot";
import { ActionTrace, TaskCard, guardrailText, stepLabel } from "./TaskCard";

function task(overrides: Partial<AgentTask> = {}): AgentTask {
  return {
    taskId: "t-1",
    conversationId: "c-1",
    engineTaskId: "TASK-0001",
    requestText: "Demand for SKU-001 will rise 20%. What should I do?",
    status: "AWAITING_APPROVAL",
    answer: "I prepared an order of 1,100 units; it is pending approval. Nothing is ordered.",
    trace: [
      {
        index: 0,
        kind: "TOOL_CALL",
        tool: "get_forecast",
        arguments: { skuId: "SKU-001", horizonWeeks: 4 },
        reason: "Need the baseline demand",
        replan: false,
        ok: true,
        errorCode: null,
        summary: "total 960 units",
      },
      {
        index: 1,
        kind: "TOOL_CALL",
        tool: "run_scenario",
        arguments: {},
        reason: "Stress the plan",
        replan: true,
        ok: false,
        errorCode: "INVALID_SCENARIO",
        summary: "accepted fields: factor",
      },
      { index: 2, kind: "FINAL", tool: null, arguments: {}, reason: "", replan: false, ok: true, errorCode: null, summary: "answer" },
    ],
    citations: [{ documentId: "POL-APPROVAL", version: "v2", excerpt: "needs manager approval" }],
    assumptions: ["demand x1.2", "4-week horizon"],
    violations: ["UNSUPPORTED_NUMBERS: 98,765"],
    recommendationId: "REC-PLAN-1",
    approvalId: "APR-0001",
    createdAt: "2024-12-30T08:00:00Z",
    ...overrides,
  };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("TaskCard", () => {
  it("folds the reasoning of a long answer behind its first line and conclusion", () => {
    const answer = ["SKU-001, 4-week horizon.", "Forecast 1,070 units.", "Plan costs 78,639.", "Pending approval."];
    renderWithSession(<TaskCard task={task({ answer: answer.join("\n") })} />);
    expect(screen.getByText("SKU-001, 4-week horizon.")).toBeVisible();
    expect(screen.getByText("Pending approval.")).toBeVisible();
    expect(screen.getByText("Show the full answer")).toBeInTheDocument();
    expect(screen.getByText("Forecast 1,070 units.")).not.toBeVisible();
  });

  it("shows the answer with its status, assumptions, evidence and next steps", () => {
    renderWithSession(<TaskCard task={task()} />);
    expect(screen.getByText("AWAITING APPROVAL")).toBeInTheDocument();
    expect(screen.getByText(/pending approval\. Nothing is ordered\./)).toBeInTheDocument();
    expect(screen.getByText("demand x1.2")).toBeInTheDocument();
    expect(screen.getByText("needs manager approval")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open recommendation REC-PLAN-1" })).toHaveAttribute(
      "href",
      "/workspace/REC-PLAN-1",
    );
    expect(screen.getByRole("link", { name: "Review approval APR-0001" })).toHaveAttribute(
      "href",
      "/approvals?open=APR-0001",
    );
    expect(screen.getByText(/Nothing has been ordered/)).toBeInTheDocument();
  });

  it("explains guardrail findings in plain words", () => {
    renderWithSession(<TaskCard task={task()} />);
    expect(screen.getByText(/contained numbers that no tool had reported/)).toBeInTheDocument();
    expect(guardrailText("APPROVAL_BYPASS")).toMatch(/skip approval was blocked/);
    expect(guardrailText("SOMETHING_NEW")).toBe("Something new");
  });

  it("summarises the trace at action level, with arguments one click deeper", async () => {
    renderWithSession(<ActionTrace steps={task().trace} />);
    expect(screen.getByText("How this was worked out (2 steps)")).toBeInTheDocument();
    expect(screen.getByText("Looked up the demand forecast")).toBeInTheDocument();
    expect(screen.getByText("Tested what could go wrong")).toBeInTheDocument();
    expect(screen.getByText(/re-planned after a result/)).toBeInTheDocument();
    expect(screen.getByText(/failed \(INVALID_SCENARIO\)/)).toBeInTheDocument();
    expect(screen.getByText(/"skuId":"SKU-001"/)).toBeInTheDocument();
  });

  it("labels every tool the agent can call", () => {
    for (const tool of [
      "get_forecast",
      "get_inventory",
      "assess_inventory_need",
      "search_suppliers",
      "get_supplier_performance",
      "search_policies",
      "optimize_procurement",
      "plan_fulfillment",
      "run_scenario",
      "prepare_purchase_order",
    ]) {
      const label = stepLabel({ ...task().trace[0], tool });
      expect(label).not.toBe(tool.replace(/_/g, " "));
    }
  });

  it("hides the approval notice for completed tasks", () => {
    renderWithSession(
      <TaskCard task={task({ status: "COMPLETED", approvalId: null, recommendationId: null, violations: [] })} />,
    );
    expect(screen.queryByText(/Nothing has been ordered/)).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: /Open recommendation/ })).not.toBeInTheDocument();
  });
});

describe("Copilot", () => {
  it("sends a request, shows the answer and keeps the conversation", async () => {
    const sent: unknown[] = [];
    stubBackend({
      "/api/agent/conversations": [],
      "/api/agent/tasks": (_url: string, init: RequestInit) => {
        sent.push(JSON.parse(init.body as string));
        return new Response(JSON.stringify(task()), { status: 201 });
      },
    });
    renderWithSession(<Copilot />);

    await userEvent.type(await screen.findByLabelText("Your question"), "What should I do about SKU-001?");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(await screen.findByText(/I prepared an order of 1,100 units/)).toBeInTheDocument();
    expect(sent[0]).toEqual({ text: "What should I do about SKU-001?" });

    await userEvent.type(screen.getByLabelText("Your question"), "And for SKU-002?");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    await screen.findAllByText(/I prepared an order/);
    expect(sent[1]).toEqual({ text: "And for SKU-002?", conversationId: "c-1" });
  });

  it("offers example questions that run when clicked", async () => {
    const { calls } = stubBackend({
      "/api/agent/conversations": [],
      "/api/agent/tasks": () => new Response(JSON.stringify(task({ status: "COMPLETED" })), { status: 201 }),
    });
    renderWithSession(<Copilot />);
    await userEvent.click(await screen.findByRole("button", { name: /expected to rise by 20%/ }));
    await screen.findByText("COMPLETED");
    expect(calls.some((c) => c.url === "/api/agent/tasks")).toBe(true);
  });

  it("shows the backend's message when the request fails", async () => {
    stubBackend({
      "/api/agent/conversations": [],
      "/api/agent/tasks": () => errorResponse(503, "ML_SERVICE_UNAVAILABLE", "ML service is unreachable"),
    });
    renderWithSession(<Copilot />);
    await userEvent.type(await screen.findByLabelText("Your question"), "hello there");
    await userEvent.click(screen.getByRole("button", { name: "Send" }));
    expect(await screen.findByText("ML service is unreachable")).toBeInTheDocument();
  });

  it("reopens an earlier conversation", async () => {
    stubBackend({
      "/api/agent/conversations/c-9": {
        conversation: { conversationId: "c-9", userId: "pat", createdAt: "2024-12-30T08:00:00Z" },
        tasks: [task({ taskId: "t-9", conversationId: "c-9", requestText: "an earlier question" })],
      },
      "/api/agent/conversations": [{ conversationId: "c-9", userId: "pat", createdAt: "2024-12-30T08:00:00Z" }],
    });
    renderWithSession(<Copilot />);
    const list = (await screen.findByRole("heading", { name: "Conversations" })).closest("section")!;
    await userEvent.click(await within(list).findByRole("button", { name: /Dec 30, 2024/ }));
    expect(await screen.findByLabelText("Request: an earlier question")).toBeInTheDocument();
  });

  it("does not send an empty request", async () => {
    stubBackend({ "/api/agent/conversations": [] });
    renderWithSession(<Copilot />);
    await screen.findByLabelText("Your question");
    expect(screen.getByRole("button", { name: "Send" })).toBeDisabled();
  });
});
