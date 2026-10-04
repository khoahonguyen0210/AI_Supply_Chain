"use client";

import { useState } from "react";
import { Panel, ResourceView } from "@/components/ui";
import { DemandForecastPanel } from "@/components/dashboard/DemandForecastPanel";
import { RecommendationsPanel, ScenariosPanel } from "@/components/dashboard/DecisionsPanel";
import { InventoryPanel } from "@/components/dashboard/InventoryPanel";
import { SupplierOptionsPanel } from "@/components/dashboard/SupplierOptionsPanel";
import { listSkus } from "@/lib/api/planning";
import type { InventoryRow, Sku } from "@/lib/api/types";
import { humanize } from "@/lib/format";
import { useSession } from "@/lib/session";
import { useResource } from "@/lib/useResource";

/** Products grouped by category, so the list reads in sections rather than one long run of codes. */
function byCategory(skus: Sku[]): [string, Sku[]][] {
  const groups = new Map<string, Sku[]>();
  for (const sku of skus) groups.set(sku.category, [...(groups.get(sku.category) ?? []), sku]);
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
}

export function Dashboard() {
  const { user, ready } = useSession();
  const { state, reload } = useResource(ready ? user.userId : null, (signal) => listSkus(signal));
  const [chosen, setChosen] = useState<string | null>(null);
  const [inventory, setInventory] = useState<InventoryRow[]>([]);

  return (
    <div className="stack">
      <div>
        <h1>Overview</h1>
        <p className="lede">Sales, stock and suppliers for one product.</p>
      </div>
      <ResourceView state={state} onRetry={reload} loadingLabel="Loading products…">
        {(skus) => {
          if (skus.length === 0) {
            return <p className="muted">No products are loaded in the database yet.</p>;
          }
          const skuId = chosen ?? skus[0].skuId;
          const sku = skus.find((s) => s.skuId === skuId) ?? skus[0];
          return (
            <>
              <Panel title="Product" id="product">
                <div className="picker">
                  <label className="field picker-select">
                    <span>Choose a product</span>
                    <select
                      value={sku.skuId}
                      onChange={(e) => {
                        setChosen(e.target.value);
                        setInventory([]);
                      }}
                    >
                      {byCategory(skus).map(([category, items]) => (
                        <optgroup key={category} label={humanize(category)}>
                          {items.map((s) => (
                            <option key={s.skuId} value={s.skuId}>
                              {s.name} ({s.skuId})
                            </option>
                          ))}
                        </optgroup>
                      ))}
                    </select>
                  </label>
                  <ul className="facts">
                    <li>{humanize(sku.category)}</li>
                    <li>${sku.unitPrice.toFixed(2)} each</li>
                    {sku.requiredCertifications.length > 0 ? (
                      <li>Needs {sku.requiredCertifications.join(", ")}</li>
                    ) : null}
                  </ul>
                </div>
              </Panel>
              <DemandForecastPanel skuId={sku.skuId} />
              <div className="grid-2">
                <InventoryPanel skuId={sku.skuId} onLoaded={setInventory} />
                <SupplierOptionsPanel skuId={sku.skuId} warehouses={inventory} />
              </div>
              <div className="grid-2">
                <RecommendationsPanel />
                <ScenariosPanel />
              </div>
            </>
          );
        }}
      </ResourceView>
    </div>
  );
}
