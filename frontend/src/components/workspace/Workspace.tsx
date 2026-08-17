"use client";

import { useState } from "react";
import type { PlanResult } from "@/lib/api/types";
import { AlternativesPanel } from "./AlternativesPanel";
import { EvidencePanel } from "./EvidencePanel";
import { PlanBuilder } from "./PlanBuilder";
import type { SolvedPlan } from "./PlanBuilder";
import { ScenarioPanel } from "./ScenarioPanel";

/** Decision workspace: build a plan, inspect it, look at alternatives, stress it and check the evidence. */
export function Workspace() {
  const [solved, setSolved] = useState<SolvedPlan | null>(null);
  const [alternatives, setAlternatives] = useState<PlanResult["lines"][number] | null>(null);

  return (
    <div className="stack">
      <div>
        <h1>Decision workspace</h1>
        <p className="lede">
          Inspect the assumptions, constraints and alternatives behind a purchase plan, see how it holds up
          under a disruption, and check the policies that apply.
        </p>
      </div>
      <PlanBuilder
        onSolved={(next) => {
          setSolved(next);
          setAlternatives(null);
        }}
        onAlternatives={setAlternatives}
      />
      {alternatives ? (
        <AlternativesPanel line={alternatives} onClose={() => setAlternatives(null)} />
      ) : null}
      <ScenarioPanel planSpec={solved?.spec ?? null} />
      <EvidencePanel />
    </div>
  );
}
