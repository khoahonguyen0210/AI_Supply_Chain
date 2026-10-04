"use client";

import { useState } from "react";
import type { PlanResult } from "@/lib/api/types";
import { AlternativesPanel } from "./AlternativesPanel";
import { EvidencePanel } from "./EvidencePanel";
import { PlanBuilder } from "./PlanBuilder";
import type { SolvedPlan } from "./PlanBuilder";
import { ScenarioPanel } from "./ScenarioPanel";

export function Workspace() {
  const [solved, setSolved] = useState<SolvedPlan | null>(null);
  const [alternatives, setAlternatives] = useState<PlanResult["lines"][number] | null>(null);

  return (
    <div className="stack">
      <div>
        <h1>Plan builder</h1>
        <p className="lede">Make a purchase plan and test what could go wrong.</p>
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
