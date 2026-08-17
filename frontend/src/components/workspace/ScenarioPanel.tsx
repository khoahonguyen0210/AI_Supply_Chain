"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { Notice, Panel } from "@/components/ui";
import { errorMessage } from "@/lib/api/client";
import { createScenario, runScenario } from "@/lib/api/decisions";
import { waitForJob } from "@/lib/api/jobs";
import type { Job, PlanSpec, ScenarioRunResult, ScenarioType } from "@/lib/api/types";
import { SCENARIO_FORMS, buildParameters, scenarioForm } from "@/lib/scenarios";
import { jobProgressLabel } from "@/lib/useJobRun";
import { ScenarioComparisonView } from "./ScenarioComparisonView";

type Run =
  | { phase: "idle" }
  | { phase: "running"; job: Job | null }
  | { phase: "done"; result: ScenarioRunResult }
  | { phase: "error"; message: string };

/** Define a disruption, save it, and stress the current plan with it (a scenario job). */
export function ScenarioPanel({ planSpec }: { planSpec: PlanSpec | null }) {
  const [type, setType] = useState<ScenarioType>("DEMAND_SHOCK");
  const [name, setName] = useState("");
  const [values, setValues] = useState<Record<string, string>>({ factor: "1.2" });
  const [run, setRun] = useState<Run>({ phase: "idle" });
  const form = scenarioForm(type);
  const built = buildParameters(type, values);
  const errors = Object.values(built.errors);

  function choose(next: ScenarioType) {
    setType(next);
    setValues({});
    setRun({ phase: "idle" });
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!planSpec || errors.length > 0) return;
    setRun({ phase: "running", job: null });
    try {
      const scenario = await createScenario(
        name.trim() || `${form.label} (${new Date().toISOString().slice(0, 10)})`,
        type,
        built.parameters,
      );
      const job = await runScenario(scenario.scenarioId, planSpec, crypto.randomUUID());
      setRun({ phase: "running", job });
      const result = await waitForJob<ScenarioRunResult>(job.id, {
        onUpdate: (update) => setRun({ phase: "running", job: update }),
      });
      setRun({ phase: "done", result });
    } catch (error) {
      setRun({ phase: "error", message: errorMessage(error) });
    }
  }

  return (
    <Panel title="Scenario stress test" id="scenario">
      {planSpec === null ? (
        <p className="muted">Optimize a plan first; scenarios are run against it.</p>
      ) : (
        <form className="stack" onSubmit={submit}>
          <div className="form-row">
            <label className="field">
              <span>Disruption</span>
              <select value={type} onChange={(e) => choose(e.target.value as ScenarioType)}>
                {SCENARIO_FORMS.map((f) => (
                  <option key={f.type} value={f.type}>
                    {f.label}
                  </option>
                ))}
              </select>
            </label>
            {form.fields.map((field) => (
              <label key={field.key} className="field">
                <span>
                  {field.label}
                  {field.required ? "" : " (optional)"}
                </span>
                <input
                  type={field.kind === "text" ? "text" : "number"}
                  min={field.min}
                  max={field.max}
                  step={field.step}
                  placeholder={field.placeholder}
                  value={values[field.key] ?? ""}
                  onChange={(e) => setValues({ ...values, [field.key]: e.target.value })}
                />
              </label>
            ))}
            <label className="field">
              <span>Name (optional)</span>
              <input value={name} onChange={(e) => setName(e.target.value)} />
            </label>
            <button
              type="submit"
              className="primary"
              disabled={run.phase === "running" || errors.length > 0}
            >
              {run.phase === "running" ? "Running…" : "Run scenario"}
            </button>
          </div>
          <p className="muted">{form.description}</p>
          {errors.length > 0 ? <Notice tone="warn">{errors[0]}</Notice> : null}
        </form>
      )}
      {run.phase === "running" ? <p role="status">{jobProgressLabel(run.job)}</p> : null}
      {run.phase === "error" ? <Notice tone="bad">{run.message}</Notice> : null}
      {run.phase === "done" ? (
        <div style={{ marginTop: 16 }}>
          <ScenarioComparisonView comparison={run.result.scenario} />
        </div>
      ) : null}
    </Panel>
  );
}
