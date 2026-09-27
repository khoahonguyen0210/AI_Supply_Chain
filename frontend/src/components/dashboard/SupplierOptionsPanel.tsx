"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { SupplierResults } from "@/components/SupplierResults";
import { Notice, Panel } from "@/components/ui";
import { errorMessage } from "@/lib/api/client";
import { searchSuppliers } from "@/lib/api/planning";
import type { InventoryRow, SupplierSearchResult } from "@/lib/api/types";

type Search =
  | { phase: "idle" }
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "done"; result: SupplierSearchResult };

export function SupplierOptionsPanel({
  skuId,
  warehouses,
}: {
  skuId: string;
  warehouses: InventoryRow[];
}) {
  const [warehouseId, setWarehouseId] = useState("");
  const [quantity, setQuantity] = useState("200");
  const [search, setSearch] = useState<Search>({ phase: "idle" });
  const warehouse = warehouseId || warehouses[0]?.warehouseId || "";
  const units = Number(quantity);
  const valid = warehouse !== "" && Number.isInteger(units) && units >= 1;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!valid) return;
    setSearch({ phase: "loading" });
    try {
      const result = await searchSuppliers({ skuId, warehouseId: warehouse, quantity: units });
      setSearch({ phase: "done", result });
    } catch (error) {
      setSearch({ phase: "error", message: errorMessage(error) });
    }
  }

  return (
    <Panel title="Supplier options" id="supplier-options">
      <form className="form-row" onSubmit={submit}>
        <label className="field">
          <span>Deliver to</span>
          <select value={warehouse} onChange={(e) => setWarehouseId(e.target.value)}>
            {warehouses.map((w) => (
              <option key={w.warehouseId} value={w.warehouseId}>
                {w.warehouseId}
              </option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Quantity (units)</span>
          <input
            type="number"
            min={1}
            step={1}
            value={quantity}
            onChange={(e) => setQuantity(e.target.value)}
            aria-invalid={!valid}
          />
        </label>
        <button type="submit" className="primary" disabled={!valid || search.phase === "loading"}>
          {search.phase === "loading" ? "Searching…" : "Compare suppliers"}
        </button>
      </form>
      {search.phase === "error" ? <Notice tone="bad">{search.message}</Notice> : null}
      {search.phase === "done" ? <SupplierResults result={search.result} /> : null}
      {search.phase === "idle" ? (
        <p className="muted">
          Find suppliers that can deliver this product.
        </p>
      ) : null}
    </Panel>
  );
}
