"use client";

import { Badge, EmptyState, Panel, ResourceView } from "@/components/ui";
import { getInventory } from "@/lib/api/planning";
import type { InventoryRow } from "@/lib/api/types";
import { formatDate, formatInt } from "@/lib/format";
import { useSession } from "@/lib/session";
import { useResource } from "@/lib/useResource";

export function InventoryTable({ rows }: { rows: InventoryRow[] }) {
  if (rows.length === 0) return <EmptyState>No stock records for this product yet.</EmptyState>;
  const total = rows.reduce(
    (sum, r) => ({
      onHand: sum.onHand + r.onHand,
      incoming: sum.incoming + r.incoming,
      safetyStock: sum.safetyStock + r.safetyStock,
    }),
    { onHand: 0, incoming: 0, safetyStock: 0 },
  );
  return (
    <div className="table-scroll">
      <table>
        <thead>
          <tr>
            <th>Warehouse</th>
            <th className="num">In stock</th>
            <th className="num">On the way</th>
            <th className="num">Safety buffer</th>
            <th>Stock level</th>
            <th>As of</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.warehouseId}>
              <td>{r.warehouseId}</td>
              <td className="num">{formatInt(r.onHand)}</td>
              <td className="num">{formatInt(r.incoming)}</td>
              <td className="num">{formatInt(r.safetyStock)}</td>
              <td>
                {r.onHand + r.incoming < r.safetyStock ? (
                  <Badge tone="bad">Below safety buffer</Badge>
                ) : (
                  <Badge tone="good">Above safety buffer</Badge>
                )}
              </td>
              <td>{formatDate(r.asOf)}</td>
            </tr>
          ))}
        </tbody>
        <tfoot>
          <tr>
            <th>Total</th>
            <td className="num">{formatInt(total.onHand)}</td>
            <td className="num">{formatInt(total.incoming)}</td>
            <td className="num">{formatInt(total.safetyStock)}</td>
            <td colSpan={2} />
          </tr>
        </tfoot>
      </table>
    </div>
  );
}

export function InventoryPanel({
  skuId,
  onLoaded,
}: {
  skuId: string;
  onLoaded?: (rows: InventoryRow[]) => void;
}) {
  const { user, ready } = useSession();
  const { state, reload } = useResource<InventoryRow[]>(
    ready ? `${user.userId}:${skuId}` : null,
    async (signal) => {
      const rows = await getInventory(skuId, signal);
      onLoaded?.(rows);
      return rows;
    },
  );
  return (
    <Panel title="Inventory" id="inventory">
      <ResourceView state={state} onRetry={reload}>
        {(rows) => <InventoryTable rows={rows} />}
      </ResourceView>
    </Panel>
  );
}
