import type { ScenarioType } from "./api/types";

export interface ScenarioField {
  /** The parameter name the planning engine's scenario contract expects. */
  key: string;
  label: string;
  kind: "number" | "integer" | "text";
  required: boolean;
  min?: number;
  max?: number;
  step?: number;
  placeholder?: string;
  help?: string;
}

export interface ScenarioForm {
  type: ScenarioType;
  label: string;
  description: string;
  fields: ScenarioField[];
}

const SCOPE_SUPPLIER: ScenarioField = {
  key: "supplier_id",
  label: "Supplier",
  kind: "text",
  required: false,
  placeholder: "all suppliers",
};

/**
 * The inputs each disruption accepts. Ranges are hints for the form; the planning engine validates the
 * values and its message is shown if they are rejected.
 */
export const SCENARIO_FORMS: ScenarioForm[] = [
  {
    type: "DEMAND_SHOCK",
    label: "Demand shock",
    description: "Customer demand changes by a factor (1.2 is +20%).",
    fields: [
      { key: "factor", label: "Demand factor", kind: "number", required: true, min: 0.1, max: 10, step: 0.05 },
      { key: "sku_id", label: "SKU", kind: "text", required: false, placeholder: "all SKUs" },
      { key: "region_id", label: "Region", kind: "text", required: false, placeholder: "all regions" },
    ],
  },
  {
    type: "SUPPLIER_OUTAGE",
    label: "Supplier outage",
    description: "A supplier cannot deliver at all.",
    fields: [{ ...SCOPE_SUPPLIER, required: true, placeholder: "SUP-001" }],
  },
  {
    type: "PRICE_SHOCK",
    label: "Price shock",
    description: "Purchase prices change by a factor (1.15 is +15%).",
    fields: [
      { key: "factor", label: "Price factor", kind: "number", required: true, min: 0.1, max: 10, step: 0.05 },
      SCOPE_SUPPLIER,
      { key: "sku_id", label: "SKU", kind: "text", required: false, placeholder: "all SKUs" },
    ],
  },
  {
    type: "CAPACITY_REDUCTION",
    label: "Supplier capacity reduction",
    description: "Suppliers can deliver only a share of their usual weekly capacity.",
    fields: [
      {
        key: "factor",
        label: "Capacity remaining",
        kind: "number",
        required: true,
        min: 0.05,
        max: 1,
        step: 0.05,
        help: "0.6 means 60% of capacity remains.",
      },
      SCOPE_SUPPLIER,
    ],
  },
  {
    type: "LEAD_TIME_SHOCK",
    label: "Lead time shock",
    description: "Deliveries take longer.",
    fields: [
      { key: "days", label: "Extra days", kind: "integer", required: true, min: 1, max: 180, step: 1 },
      SCOPE_SUPPLIER,
    ],
  },
  {
    type: "WAREHOUSE_CAPACITY_REDUCTION",
    label: "Warehouse capacity reduction",
    description: "Warehouses can hold only a share of their usual capacity.",
    fields: [
      {
        key: "factor",
        label: "Capacity remaining",
        kind: "number",
        required: true,
        min: 0.05,
        max: 1,
        step: 0.05,
      },
      { key: "warehouse_id", label: "Warehouse", kind: "text", required: false, placeholder: "all warehouses" },
    ],
  },
  {
    type: "TRANSPORT_COST_SHOCK",
    label: "Transport cost shock",
    description: "Shipping costs change by a factor.",
    fields: [
      { key: "factor", label: "Cost factor", kind: "number", required: true, min: 0.1, max: 10, step: 0.05 },
      SCOPE_SUPPLIER,
    ],
  },
];

export function scenarioForm(type: ScenarioType): ScenarioForm {
  const form = SCENARIO_FORMS.find((f) => f.type === type);
  if (!form) throw new Error(`unknown scenario type ${type}`);
  return form;
}

export interface BuiltParameters {
  parameters: Record<string, number | string>;
  errors: Record<string, string>;
}

/** Turns the form's text values into engine parameters; empty optional fields are left out. */
export function buildParameters(type: ScenarioType, values: Record<string, string>): BuiltParameters {
  const parameters: Record<string, number | string> = {};
  const errors: Record<string, string> = {};
  for (const field of scenarioForm(type).fields) {
    const raw = (values[field.key] ?? "").trim();
    if (raw === "") {
      if (field.required) errors[field.key] = `${field.label} is required`;
      continue;
    }
    if (field.kind === "text") {
      parameters[field.key] = raw;
      continue;
    }
    const value = Number(raw);
    if (!Number.isFinite(value)) {
      errors[field.key] = `${field.label} must be a number`;
    } else if (field.kind === "integer" && !Number.isInteger(value)) {
      errors[field.key] = `${field.label} must be a whole number`;
    } else {
      parameters[field.key] = value;
    }
  }
  return { parameters, errors };
}
