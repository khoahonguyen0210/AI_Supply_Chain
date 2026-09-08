const number0 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 });
const number1 = new Intl.NumberFormat("en-US", { maximumFractionDigits: 1 });
const money0 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  maximumFractionDigits: 0,
});
const money2 = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export const formatInt = (value: number) => number0.format(value);
export const formatNumber = (value: number) => number1.format(value);
export const formatMoney = (value: number) => money0.format(value);
export const formatUnitPrice = (value: number) => money2.format(value);

/** A fraction as a percentage: 0.973 -> "97.3%". */
export const formatPercent = (fraction: number, digits = 1) =>
  `${(fraction * 100).toFixed(digits)}%`;

/** A signed money amount: positive values get a leading "+". */
export function formatSignedMoney(value: number): string {
  const formatted = money0.format(Math.abs(value));
  if (value > 0) return `+${formatted}`;
  if (value < 0) return `-${formatted}`;
  return formatted;
}

export function formatSignedPercentPoints(fractionDelta: number): string {
  const points = fractionDelta * 100;
  const text = `${Math.abs(points).toFixed(1)} pts`;
  if (points > 0.05) return `+${text}`;
  if (points < -0.05) return `-${text}`;
  return "0.0 pts";
}

export const formatDate = (iso: string) => iso.slice(0, 10);

export function formatDateTime(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) return iso;
  return date.toLocaleString("en-US", { dateStyle: "medium", timeStyle: "short" });
}

/** "procurement_manager" -> "Procurement manager". */
export function humanize(value: string): string {
  const text = value.replace(/_/g, " ").toLowerCase();
  return text.charAt(0).toUpperCase() + text.slice(1);
}
