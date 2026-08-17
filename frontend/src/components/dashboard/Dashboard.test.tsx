import { screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { errorResponse, renderWithSession, stubBackend } from "@/test/render";
import type { DemandPoint, ForecastResponse } from "@/lib/api/types";
import { Dashboard } from "./Dashboard";
import { forecastBand, weeklyHistory } from "./DemandForecastPanel";

const SKUS = [
  {
    skuId: "SKU-001",
    name: "Widget",
    category: "home",
    unitPrice: 20,
    unitVolume: 0.1,
    requiredCertifications: ["ISO9001"],
  },
  {
    skuId: "SKU-002",
    name: "Gadget",
    category: "home",
    unitPrice: 35,
    unitVolume: 0.2,
    requiredCertifications: [],
  },
];

const WEEKS = ["2024-12-09", "2024-12-16", "2024-12-23"];

function demand(sku: string): DemandPoint[] {
  return WEEKS.flatMap((periodStart, i) => [
    { skuId: sku, regionId: "R1", periodStart, quantity: 10 + i },
    { skuId: sku, regionId: "R2", periodStart, quantity: 20 + i },
  ]);
}

function forecast(regionId: string, base: number): ForecastResponse {
  return {
    schemaVersion: "1",
    modelVersion: "lgbm-test",
    datasetId: "ds",
    skuId: "SKU-001",
    regionId,
    asOf: "2024-12-30",
    intervalLevel: 0.8,
    method: "lightgbm-cqr",
    points: [
      { weekStart: "2024-12-30", horizon: 1, point: base, lower: base - 4, upper: base + 6 },
      { weekStart: "2025-01-06", horizon: 2, point: base + 1, lower: base - 3, upper: base + 7 },
    ],
  };
}

const INVENTORY = [
  { skuId: "SKU-001", warehouseId: "W1", asOf: "2024-12-30T00:00:00Z", onHand: 80, incoming: 20, safetyStock: 10 },
  { skuId: "SKU-001", warehouseId: "W2", asOf: "2024-12-30T00:00:00Z", onHand: 2, incoming: 0, safetyStock: 30 },
];

const SEARCH = {
  skuId: "SKU-001",
  warehouseId: "W1",
  quantity: 200,
  maxLeadTimeDays: 28,
  eligibleCount: 1,
  ranked: [
    {
      rank: 1,
      supplierId: "SUP-1",
      supplierName: "Acme",
      landedUnitCost: 12.9,
      totalCost: 2580,
      costVsCheapestPct: 0,
      leadTimeDays: 7,
      reliability: 0.95,
      qualityScore: 0.9,
    },
  ],
  rejected: { "SUP-2": ["MISSING_CERTIFICATION"] },
  cheapestOverall: {
    supplierId: "SUP-2",
    landedUnitCost: 9.5,
    eligible: false,
    rejectionReasons: ["MISSING_CERTIFICATION"],
  },
  tradeOffs: ["Acme costs more but is more reliable"],
};

function backend(overrides: Record<string, unknown> = {}) {
  return stubBackend({
    "/api/skus": SKUS,
    "/api/demand": (url: string) => demand(new URL(url, "http://x").searchParams.get("skuId") ?? ""),
    "/api/forecasts": (_url: string, init: RequestInit) => {
      const body = JSON.parse(init.body as string) as { regionId: string };
      return forecast(body.regionId, body.regionId === "R1" ? 12 : 25);
    },
    "/api/inventory": INVENTORY,
    "/api/suppliers/search": SEARCH,
    "/api/recommendations": [
      {
        recommendationId: "REC-1",
        createdAt: "2024-12-30T08:00:00Z",
        summary: "Buy 100 widgets from Acme",
        objectiveValue: 1290,
        expectedServiceLevel: 0.97,
        assumptions: [],
        citations: [],
        horizonStart: "2024-12-30",
        horizonEnd: "2025-01-27",
        status: "PENDING_APPROVAL",
      },
    ],
    "/api/scenarios": [],
    ...overrides,
  });
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("dashboard data shaping", () => {
  it("sums regions into one weekly history, oldest first", () => {
    const history = weeklyHistory(demand("S"), "ALL");
    expect(history).toEqual([
      { date: "2024-12-09", value: 30 },
      { date: "2024-12-16", value: 32 },
      { date: "2024-12-23", value: 34 },
    ]);
    expect(weeklyHistory(demand("S"), "R2").map((p) => p.value)).toEqual([20, 21, 22]);
  });

  it("keeps a region's interval but sums regions by point", () => {
    const all = [forecast("R1", 12), forecast("R2", 25)];
    expect(forecastBand(all, "R1")[0]).toMatchObject({ point: 12, lower: 8, upper: 18 });
    expect(forecastBand(all, "ALL").map((p) => p.point)).toEqual([37, 39]);
  });
});

describe("Dashboard", () => {
  it("shows demand, forecast, inventory, recommendations and scenarios for the first SKU", async () => {
    backend();
    renderWithSession(<Dashboard />);

    expect(await screen.findByRole("heading", { name: "Demand and forecast" })).toBeInTheDocument();
    expect(await screen.findByText(/Model lgbm-test/)).toBeInTheDocument();
    expect(screen.getByRole("img", { name: /forecast to 2025-01-06/ })).toBeInTheDocument();
    expect(await screen.findByText("Buy 100 widgets from Acme")).toBeInTheDocument();
    expect(screen.getByText("PENDING APPROVAL")).toBeInTheDocument();
    expect(await screen.findByText(/No saved scenarios/)).toBeInTheDocument();

    expect(await screen.findByText("Below safety stock")).toBeInTheDocument();
    expect(screen.getByText("Above safety stock")).toBeInTheDocument();
  });

  it("sends the signed-in user's identity with every request", async () => {
    const { calls } = backend();
    renderWithSession(<Dashboard />);
    await screen.findByText(/Model lgbm-test/);
    for (const call of calls) {
      const headers = call.init.headers as Record<string, string>;
      expect(headers["X-User-Id"]).toBe("pat");
      expect(headers["X-User-Role"]).toBe("planner");
    }
  });

  it("explains that summed regions have no prediction interval", async () => {
    backend();
    renderWithSession(<Dashboard />);
    expect(await screen.findByText(/cannot be added together/)).toBeInTheDocument();

    await userEvent.selectOptions(screen.getByLabelText("Region"), "R1");
    expect(screen.queryByText(/cannot be added together/)).not.toBeInTheDocument();
    expect(await screen.findByText("80% interval")).toBeInTheDocument();
  });

  it("compares suppliers for the chosen warehouse and quantity and warns about an ineligible cheapest", async () => {
    const { calls } = backend();
    renderWithSession(<Dashboard />);
    await screen.findByText("Below safety stock");

    await userEvent.clear(screen.getByLabelText("Quantity (units)"));
    await userEvent.type(screen.getByLabelText("Quantity (units)"), "200");
    await userEvent.click(screen.getByRole("button", { name: "Compare suppliers" }));

    const alert = await screen.findByText(/is not eligible: Missing certification/);
    expect(alert).toHaveTextContent("SUP-2");
    const panel = screen.getByRole("heading", { name: "Supplier options" }).closest("section")!;
    expect(within(panel).getByText("Acme")).toBeInTheDocument();
    expect(within(panel).getByText("Acme costs more but is more reliable")).toBeInTheDocument();

    const search = calls.find((c) => c.url === "/api/suppliers/search")!;
    expect(JSON.parse(search.init.body as string)).toEqual({
      skuId: "SKU-001",
      warehouseId: "W1",
      quantity: 200,
    });
  });

  it("shows the backend's message when a panel fails and recovers on retry", async () => {
    let fail = true;
    backend({
      "/api/inventory": () =>
        fail ? errorResponse(503, "ML_SERVICE_UNAVAILABLE", "ML service is unreachable") : INVENTORY,
    });
    renderWithSession(<Dashboard />);

    const alert = await screen.findByText(/ML service is unreachable/);
    expect(alert).toBeInTheDocument();
    fail = false;
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    await waitFor(() => expect(screen.getByText("Below safety stock")).toBeInTheDocument());
  });

  it("explains an empty database instead of rendering broken panels", async () => {
    stubBackend({ "/api/skus": [] });
    renderWithSession(<Dashboard />);
    expect(await screen.findByText(/No products are loaded/)).toBeInTheDocument();
  });
});
