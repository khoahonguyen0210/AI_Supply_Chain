import { screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { errorResponse, renderWithSession, stubBackend } from "@/test/render";
import type { Approval, ApprovalDetail } from "@/lib/api/types";
import { Approvals } from "./Approvals";

let search = "";
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(search),
  usePathname: () => "/approvals",
}));

const PENDING: Approval = {
  approvalId: "APR-1",
  recommendationId: "REC-1",
  requestedBy: "pat",
  requesterRole: "planner",
  requiredRoles: ["procurement_manager", "finance"],
  approvedRoles: ["procurement_manager"],
  approvers: ["mia"],
  orderValue: 79000,
  status: "PENDING",
  createdAt: "2024-12-30T08:00:00Z",
  updatedAt: "2024-12-30T09:00:00Z",
};

function detail(approval: Approval, decisions: ApprovalDetail["decisions"] = []): ApprovalDetail {
  return {
    approval,
    decisions,
    recommendation: {
      recommendation: {
        recommendationId: "REC-1",
        createdAt: "2024-12-30T08:00:00Z",
        summary: "Buy 1100 widgets from Acme",
        objectiveValue: 18250,
        expectedServiceLevel: 0.97,
        assumptions: [],
        citations: [],
        horizonStart: "2024-12-30",
        horizonEnd: "2025-01-27",
        status: "PENDING_APPROVAL",
      },
      lines: [
        { lineNo: 1, supplierId: "SUP-1", skuId: "SKU-001", warehouseId: "W1", quantity: 1100, unitPrice: 14.36, shippingCost: 440 },
      ],
      approval,
      decisions,
    },
  };
}

beforeEach(() => {
  search = "";
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Approvals", () => {
  it("lists pending approvals with who they are waiting for", async () => {
    const { calls } = stubBackend({ "/api/approvals": [PENDING] });
    renderWithSession(<Approvals />);
    expect(await screen.findByRole("button", { name: "APR-1" })).toBeInTheDocument();
    expect(screen.getByText("$79,000")).toBeInTheDocument();
    expect(screen.getByText("Finance")).toBeInTheDocument();
    expect(calls[0].url).toBe("/api/approvals?status=PENDING");
  });

  it("opens the approval named in the URL and shows its lines and progress", async () => {
    search = "open=APR-1";
    stubBackend({
      "/api/approvals/APR-1": detail(PENDING, [
        { decisionId: "APR-1-D001", decidedBy: "mia", approverRole: "procurement_manager", outcome: "APPROVED", decidedAt: "2024-12-30T09:00:00Z", rationale: "within budget" },
      ]),
      "/api/approvals": [PENDING],
    });
    renderWithSession(<Approvals />);
    expect(await screen.findByText("Buy 1100 widgets from Acme")).toBeInTheDocument();
    expect(screen.getByText("Procurement manager approved")).toBeInTheDocument();
    expect(screen.getByText("Finance needed")).toBeInTheDocument();
    expect(screen.getByText(/mia \(Procurement manager\) approved — within budget/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeInTheDocument();
  });

  it("sends an approval with the rationale and refreshes", async () => {
    search = "open=APR-1";
    let approved = false;
    const { calls } = stubBackend({
      "/api/approvals/APR-1/decision": () => {
        approved = true;
        return detail({ ...PENDING, status: "APPROVED", approvedRoles: ["procurement_manager", "finance"] });
      },
      "/api/approvals/APR-1": () => detail(approved ? { ...PENDING, status: "APPROVED" } : PENDING),
      "/api/approvals": () => [approved ? { ...PENDING, status: "APPROVED" } : PENDING],
    });
    renderWithSession(<Approvals />);
    await userEvent.type(await screen.findByLabelText("Rationale (optional)"), "ok to proceed");
    await userEvent.click(screen.getByRole("button", { name: "Approve" }));

    expect(await screen.findByText(/Approved purchase orders were created/)).toBeInTheDocument();
    const decision = calls.find((c) => c.url === "/api/approvals/APR-1/decision")!;
    expect(JSON.parse(decision.init.body as string)).toEqual({ outcome: "APPROVED", rationale: "ok to proceed" });
  });

  it("shows the engine's reason when it refuses a decision", async () => {
    search = "open=APR-1";
    stubBackend({
      "/api/approvals/APR-1/decision": () =>
        errorResponse(403, "NOT_AUTHORIZED", "role planner cannot decide this approval; needs finance"),
      "/api/approvals/APR-1": detail(PENDING),
      "/api/approvals": [PENDING],
    });
    renderWithSession(<Approvals />);
    await userEvent.click(await screen.findByRole("button", { name: "Reject" }));
    expect(await screen.findByText(/cannot decide this approval; needs finance/)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Approve" })).toBeEnabled();
  });

  it("offers no decision on an approval that is already decided", async () => {
    search = "open=APR-1";
    stubBackend({
      "/api/approvals/APR-1": detail({ ...PENDING, status: "REJECTED" }),
      "/api/approvals": [{ ...PENDING, status: "REJECTED" }],
    });
    renderWithSession(<Approvals />);
    expect(await screen.findByText(/This approval is rejected\. No purchase order was created\./)).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Approve" })).not.toBeInTheDocument();
  });

  it("switches the queue filter", async () => {
    const { calls } = stubBackend({ "/api/approvals": [] });
    renderWithSession(<Approvals />);
    expect(await screen.findByText("Nothing to show.")).toBeInTheDocument();
    const queue = screen.getByRole("heading", { name: "Queue" }).closest("section")!;
    await userEvent.selectOptions(within(queue).getByRole("combobox"), "ALL");
    await screen.findByText("Nothing to show.");
    expect(calls.map((c) => c.url)).toContain("/api/approvals");
  });
});
