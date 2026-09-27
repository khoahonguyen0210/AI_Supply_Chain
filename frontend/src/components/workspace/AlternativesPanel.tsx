"use client";

import { useEffect, useState } from "react";
import { SupplierResults } from "@/components/SupplierResults";
import { Notice, Panel } from "@/components/ui";
import { errorMessage } from "@/lib/api/client";
import { searchSuppliers } from "@/lib/api/planning";
import type { PlanResult, SupplierSearchResult } from "@/lib/api/types";
import { formatInt } from "@/lib/format";

type Load =
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "done"; result: SupplierSearchResult };

export function AlternativesPanel({
  line,
  onClose,
}: {
  line: PlanResult["lines"][number];
  onClose: () => void;
}) {
  const [load, setLoad] = useState<Load>({ phase: "loading" });

  useEffect(() => {
    let cancelled = false;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- show loading before the request starts
    setLoad({ phase: "loading" });
    searchSuppliers({ skuId: line.skuId, warehouseId: line.warehouseId, quantity: line.quantity })
      .then((result) => !cancelled && setLoad({ phase: "done", result }))
      .catch((error: unknown) => !cancelled && setLoad({ phase: "error", message: errorMessage(error) }));
    return () => {
      cancelled = true;
    };
  }, [line.skuId, line.warehouseId, line.quantity]);

  return (
    <Panel
      title={`Alternatives for ${line.skuId} at ${line.warehouseId}`}
      id="alternatives"
      actions={
        <button type="button" onClick={onClose}>
          Close
        </button>
      }
    >
      <p className="muted">
        Other suppliers that could deliver these {formatInt(line.quantity)} units:
      </p>
      {load.phase === "loading" ? <p role="status">Comparing suppliers…</p> : null}
      {load.phase === "error" ? <Notice tone="bad">{load.message}</Notice> : null}
      {load.phase === "done" ? <SupplierResults result={load.result} /> : null}
    </Panel>
  );
}
