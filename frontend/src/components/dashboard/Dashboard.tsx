"use client";

import { useState } from "react";
import { Panel, ResourceView } from "@/components/ui";
import { DemandForecastPanel } from "@/components/dashboard/DemandForecastPanel";
import { RecommendationsPanel, ScenariosPanel } from "@/components/dashboard/DecisionsPanel";
import { InventoryPanel } from "@/components/dashboard/InventoryPanel";
import { ProductPicker } from "@/components/dashboard/ProductPicker";
import { SupplierOptionsPanel } from "@/components/dashboard/SupplierOptionsPanel";
import { listSkus } from "@/lib/api/planning";
import type { InventoryRow } from "@/lib/api/types";
import { useSession } from "@/lib/session";
import { useResource } from "@/lib/useResource";

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
              <Panel title="Choose a product" id="product">
                <ProductPicker
                  skus={skus}
                  selected={sku}
                  onSelect={(next) => {
                    setChosen(next);
                    setInventory([]);
                  }}
                />
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
