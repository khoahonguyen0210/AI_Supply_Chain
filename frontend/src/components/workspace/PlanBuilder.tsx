"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { Notice, Panel, ResourceView } from "@/components/ui";
import { listSkus } from "@/lib/api/planning";
import type { PlanResult, PlanSpec } from "@/lib/api/types";
import { useSession } from "@/lib/session";
import { jobProgressLabel, useJobRun } from "@/lib/useJobRun";
import { useResource } from "@/lib/useResource";
import { PlanAssumptions, PlanView } from "./PlanView";

const MAX_SKUS = 5;

export interface SolvedPlan {
  spec: PlanSpec;
  plan: PlanResult;
}

export function PlanBuilder({
  onSolved,
  onAlternatives,
}: {
  onSolved: (solved: SolvedPlan) => void;
  onAlternatives: (line: PlanResult["lines"][number]) => void;
}) {
  const { user, ready } = useSession();
  const skus = useResource(ready ? user.userId : null, (signal) => listSkus(signal));
  const { state, run } = useJobRun<PlanResult>();
  const [selected, setSelected] = useState<string[]>([]);
  const [horizon, setHorizon] = useState("4");
  const [multiplier, setMultiplier] = useState("1");
  const [budget, setBudget] = useState("");
  const [serviceLevel, setServiceLevel] = useState("95");
  const [spec, setSpec] = useState<PlanSpec | null>(null);

  const problems: string[] = [];
  if (selected.length === 0) problems.push("Choose at least one product.");
  if (selected.length > MAX_SKUS) problems.push(`Choose at most ${MAX_SKUS} products.`);
  if (!(Number(horizon) >= 1 && Number(horizon) <= 8)) problems.push("Plan for 1 to 8 weeks.");
  if (!(Number(multiplier) > 0)) problems.push("Demand change must be above 0.");
  if (budget !== "" && !(Number(budget) > 0)) problems.push("Budget must be above 0.");
  if (!(Number(serviceLevel) >= 50 && Number(serviceLevel) <= 100)) {
    problems.push("Share of demand to cover must be 50 to 100%.");
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (problems.length > 0) return;
    const next: PlanSpec = {
      skuIds: selected,
      horizonWeeks: Number(horizon),
      demandMultiplier: Number(multiplier),
      serviceLevel: Number(serviceLevel) / 100,
      ...(budget !== "" ? { budget: Number(budget) } : {}),
    };
    setSpec(next);
    const plan = await run("OPTIMIZATION", next);
    if (plan) onSolved({ spec: next, plan });
  }

  function toggle(skuId: string) {
    setSelected((current) =>
      current.includes(skuId) ? current.filter((s) => s !== skuId) : [...current, skuId],
    );
  }

  const running = state.phase === "running";
  return (
    <Panel title="Build a purchase plan" id="plan">
      <form className="stack" onSubmit={submit}>
        <fieldset className="field" style={{ border: "none", padding: 0, margin: 0 }}>
          <legend className="muted">Products (up to {MAX_SKUS})</legend>
          <ResourceView state={skus.state} onRetry={skus.reload}>
            {(rows) => (
              <div
                className="row"
                style={{ maxHeight: 120, overflowY: "auto", alignItems: "flex-start" }}
              >
                {rows.map((s) => (
                  <label key={s.skuId} className="row" style={{ gap: 4 }}>
                    <input
                      type="checkbox"
                      checked={selected.includes(s.skuId)}
                      onChange={() => toggle(s.skuId)}
                    />
                    {s.skuId}
                  </label>
                ))}
              </div>
            )}
          </ResourceView>
        </fieldset>
        <div className="form-row">
          <label className="field">
            <span>Weeks to plan for</span>
            <input type="number" min={1} max={8} value={horizon} onChange={(e) => setHorizon(e.target.value)} />
          </label>
          <label className="field">
            <span>Demand change (1.2 = +20%)</span>
            <input
              type="number"
              min={0.1}
              step={0.05}
              value={multiplier}
              onChange={(e) => setMultiplier(e.target.value)}
            />
          </label>
          <label className="field">
            <span>Share of demand to cover (%)</span>
            <input
              type="number"
              min={50}
              max={100}
              value={serviceLevel}
              onChange={(e) => setServiceLevel(e.target.value)}
            />
          </label>
          <label className="field">
            <span>Budget in USD (optional)</span>
            <input type="number" min={1} value={budget} onChange={(e) => setBudget(e.target.value)} />
          </label>
          <button type="submit" className="primary" disabled={running || problems.length > 0}>
            {running ? "Building…" : "Build plan"}
          </button>
        </div>
        {problems.length > 0 && selected.length > 0 ? <Notice tone="warn">{problems[0]}</Notice> : null}
      </form>

      {state.phase === "running" ? <p role="status">{jobProgressLabel(state.job)}</p> : null}
      {state.phase === "error" ? <Notice tone="bad">{state.message}</Notice> : null}
      {state.phase === "done" && spec ? (
        <div className="stack" style={{ marginTop: 16 }}>
          <PlanAssumptions spec={spec} plan={state.result} />
          <PlanView plan={state.result} onAlternatives={onAlternatives} />
        </div>
      ) : null}
    </Panel>
  );
}
