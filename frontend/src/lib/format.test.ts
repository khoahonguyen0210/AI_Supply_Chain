import { describe, expect, it } from "vitest";
import { nextWeekStart } from "./api/planning";
import {
  formatMoney,
  formatPercent,
  formatSignedMoney,
  formatSignedPercentPoints,
  humanize,
} from "./format";

describe("format", () => {
  it("formats money and percentages", () => {
    expect(formatMoney(12345.6)).toBe("$12,346");
    expect(formatPercent(0.9734)).toBe("97.3%");
  });

  it("signs deltas", () => {
    expect(formatSignedMoney(1500)).toBe("+$1,500");
    expect(formatSignedMoney(-1500)).toBe("-$1,500");
    expect(formatSignedMoney(0)).toBe("$0");
    expect(formatSignedPercentPoints(-0.0312)).toBe("-3.1 pts");
    expect(formatSignedPercentPoints(0.0001)).toBe("0.0 pts");
  });

  it("humanizes identifiers", () => {
    expect(humanize("procurement_manager")).toBe("Procurement manager");
    expect(humanize("AWAITING_APPROVAL")).toBe("Awaiting approval");
  });
});

describe("nextWeekStart", () => {
  it("is the Monday after the last observed week", () => {
    expect(nextWeekStart("2024-12-23")).toBe("2024-12-30");
    expect(nextWeekStart("2024-12-30")).toBe("2025-01-06");
  });
});
