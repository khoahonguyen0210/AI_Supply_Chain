import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { TimeSeriesChart } from "./TimeSeriesChart";

const history = [
  { date: "2024-12-09", value: 10 },
  { date: "2024-12-16", value: 14 },
  { date: "2024-12-23", value: 12 },
];
const forecast = [
  { date: "2024-12-30", point: 13, lower: 6, upper: 22 },
  { date: "2025-01-06", point: 14, lower: 7, upper: 24 },
];

describe("TimeSeriesChart", () => {
  it("draws history, forecast and the interval band with an accessible summary", () => {
    const { container } = render(
      <TimeSeriesChart history={history} forecast={forecast} intervalLevel={0.8} />,
    );
    const chart = screen.getByRole("img");
    expect(chart).toHaveAccessibleName(/from 2024-12-09, forecast to 2025-01-06, likely range 80%/);
    expect(container.querySelector(".chart-history")).not.toBeNull();
    expect(container.querySelector(".chart-forecast")).not.toBeNull();
    expect(container.querySelector(".chart-band")).not.toBeNull();
    expect(screen.getByText("Likely range (80%)")).toBeInTheDocument();
  });

  it("renders history alone without a band", () => {
    const { container } = render(<TimeSeriesChart history={history} forecast={[]} />);
    expect(container.querySelector(".chart-forecast")).toBeNull();
    expect(container.querySelector(".chart-band")).toBeNull();
  });

  it("says so when there is nothing to chart", () => {
    render(<TimeSeriesChart history={[]} forecast={[]} />);
    expect(screen.getByText("No data to chart.")).toBeInTheDocument();
  });
});
