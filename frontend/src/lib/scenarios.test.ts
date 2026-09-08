import { describe, expect, it } from "vitest";
import { SCENARIO_FORMS, buildParameters, scenarioForm } from "./scenarios";

describe("scenario forms", () => {
  it("covers every scenario type the backend supports", () => {
    expect(SCENARIO_FORMS.map((f) => f.type).sort()).toEqual([
      "CAPACITY_REDUCTION",
      "DEMAND_SHOCK",
      "LEAD_TIME_SHOCK",
      "PRICE_SHOCK",
      "SUPPLIER_OUTAGE",
      "TRANSPORT_COST_SHOCK",
      "WAREHOUSE_CAPACITY_REDUCTION",
    ]);
  });

  it("uses the engine's parameter names", () => {
    expect(scenarioForm("DEMAND_SHOCK").fields.map((f) => f.key)).toEqual([
      "factor",
      "sku_id",
      "region_id",
    ]);
    expect(scenarioForm("LEAD_TIME_SHOCK").fields.map((f) => f.key)).toEqual(["days", "supplier_id"]);
  });
});

describe("buildParameters", () => {
  it("parses numbers, keeps text and drops empty optional fields", () => {
    const built = buildParameters("DEMAND_SHOCK", { factor: "1.5", sku_id: " SKU-001 ", region_id: "" });
    expect(built.errors).toEqual({});
    expect(built.parameters).toEqual({ factor: 1.5, sku_id: "SKU-001" });
  });

  it("requires the required fields", () => {
    const built = buildParameters("SUPPLIER_OUTAGE", {});
    expect(built.errors).toEqual({ supplier_id: "Supplier is required" });
  });

  it("rejects non-numbers and fractional day counts", () => {
    expect(buildParameters("DEMAND_SHOCK", { factor: "abc" }).errors.factor).toMatch(/must be a number/);
    expect(buildParameters("LEAD_TIME_SHOCK", { days: "2.5" }).errors.days).toMatch(/whole number/);
    expect(buildParameters("LEAD_TIME_SHOCK", { days: "14" }).parameters).toEqual({ days: 14 });
  });
});
