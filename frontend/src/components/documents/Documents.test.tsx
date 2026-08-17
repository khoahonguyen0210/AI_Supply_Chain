import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithSession, stubBackend } from "@/test/render";
import { Documents } from "./Documents";

let search = "";
vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(search),
  usePathname: () => "/documents",
}));

const LIST = [
  {
    documentId: "POL-1",
    version: "v2",
    docType: "POLICY",
    title: "Purchase order approvals",
    effectiveDate: "2024-07-01",
    expiryDate: null,
    supplierId: null,
    inForce: true,
  },
  {
    documentId: "POL-1",
    version: "v1",
    docType: "POLICY",
    title: "Purchase order approvals",
    effectiveDate: "2024-01-01",
    expiryDate: "2024-06-30",
    supplierId: null,
    inForce: false,
  },
];

beforeEach(() => {
  search = "";
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Documents", () => {
  it("lists the documents with their validity", async () => {
    const { calls } = stubBackend({ "/api/documents": [LIST[0]] });
    renderWithSession(<Documents />);
    expect(await screen.findByRole("button", { name: "Purchase order approvals" })).toBeInTheDocument();
    expect(screen.getByText("in force")).toBeInTheDocument();
    expect(calls[0].url).toBe("/api/documents?includeSuperseded=false");
  });

  it("reads a document and shows who may read it", async () => {
    stubBackend({
      "/api/documents/POL-1": {
        summary: LIST[0],
        allowedRoles: ["planner", "admin"],
        content: "Orders above USD 15,000 require procurement manager approval.",
      },
      "/api/documents": [LIST[0]],
    });
    renderWithSession(<Documents />);
    await userEvent.click(await screen.findByRole("button", { name: "Purchase order approvals" }));
    expect(await screen.findByText(/Orders above USD 15,000 require/)).toBeInTheDocument();
    expect(screen.getByText(/readable by Planner, Admin/)).toBeInTheDocument();
  });

  it("opens the cited version straight from a link and includes superseded versions", async () => {
    search = "open=POL-1&version=v1";
    const { calls } = stubBackend({
      "/api/documents/POL-1": { summary: LIST[1], allowedRoles: ["planner"], content: "old rule text" },
      "/api/documents": LIST,
    });
    renderWithSession(<Documents />);
    expect(await screen.findByText("old rule text")).toBeInTheDocument();
    expect(await screen.findByText("superseded")).toBeInTheDocument();
    expect(calls.some((c) => c.url === "/api/documents/POL-1?version=v1")).toBe(true);
  });

  it("says when the role can read nothing", async () => {
    stubBackend({ "/api/documents": [] });
    renderWithSession(<Documents />);
    expect(await screen.findByText(/No documents are available to your role/)).toBeInTheDocument();
  });
});
