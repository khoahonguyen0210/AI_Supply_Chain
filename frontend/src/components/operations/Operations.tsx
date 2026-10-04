"use client";

import { Badge, Notice, Panel, ResourceView, Stat } from "@/components/ui";
import { getAiTelemetry, getOpsSummary } from "@/lib/api/decisions";
import type { AiQuality, AiRuntime, OpsSummary } from "@/lib/api/types";
import { formatInt, formatNumber, formatPercent, humanize } from "@/lib/format";
import { useSession } from "@/lib/session";
import { useResource } from "@/lib/useResource";

const NOT_MEASURED = "NOT YET MEASURED";

const ms = (value: number) => `${formatNumber(value)} ms`;
const share = (value: number | null | undefined) =>
  value === null || value === undefined ? "—" : formatPercent(value);

export function SystemSection({ summary }: { summary: OpsSummary }) {
  const { api, queue } = summary;
  return (
    <div className="stack">
      <dl className="stats">
        <Stat label="API requests" value={formatInt(api.requests)} hint={`${formatNumber(api.requestsPerSecond)} / s over uptime`} />
        <Stat label="Server error rate" value={formatPercent(api.errorRate, 2)} hint={`${formatInt(api.serverErrors)} server, ${formatInt(api.clientErrors)} client errors`} />
        <Stat label="Typical response time" value={ms(api.p50Millis)} />
        <Stat label="Slowest 5% response time" value={ms(api.p95Millis)} />
      </dl>
      <dl className="stats">
        <Stat label="Queued" value={formatInt(queue.byStatus.QUEUED ?? 0)} hint={`oldest waiting ${formatNumber(queue.oldestQueuedSeconds)} s`} />
        <Stat label="Running" value={formatInt(queue.byStatus.RUNNING ?? 0)} />
        <Stat label="Succeeded" value={formatInt(queue.byStatus.SUCCEEDED ?? 0)} />
        <Stat label="Failed" value={formatInt(queue.byStatus.FAILED ?? 0)} />
        <Stat label="Worker busy time" value={formatPercent(queue.workerUtilization)} hint="this instance, over uptime" />
      </dl>
      <div className="table-scroll">
        <table>
          <caption className="muted" style={{ textAlign: "left" }}>
            Job attempts by type (since this instance started)
          </caption>
          <thead>
            <tr>
              <th>Type</th>
              <th className="num">Mean duration</th>
              <th className="num">Failed attempts</th>
            </tr>
          </thead>
          <tbody>
            {Object.keys(queue.meanDurationMillis).map((type) => (
              <tr key={type}>
                <td>{humanize(type)}</td>
                <td className="num">{ms(queue.meanDurationMillis[type])}</td>
                <td className="num">{formatInt(queue.failedAttempts[type] ?? 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Counts({ counts }: { counts: Record<string, number> }) {
  const entries = Object.entries(counts);
  if (entries.length === 0) return <span className="muted">none yet</span>;
  return (
    <>
      {entries.map(([key, value]) => (
        <span key={key} style={{ marginRight: 12 }}>
          {humanize(key.replace(":", " – "))}: {formatInt(value)}
        </span>
      ))}
    </>
  );
}

export function RuntimeSection({ runtime }: { runtime: AiRuntime }) {
  const models = Object.entries(runtime.models);
  return (
    <div className="stack">
      <dl className="stats">
        <Stat label="Forecast calls" value={formatInt(runtime.forecast.count)} hint={`p95 ${ms(runtime.forecast.p95Millis)}`} />
        <Stat label="Tool-call success" value={share(runtime.tools.successRate)} hint={`${formatInt(runtime.tools.calls)} calls`} />
        <Stat label="Agent tasks" value={formatInt(runtime.agent.count)} hint={`p95 ${ms(runtime.agent.p95Millis)}`} />
        <Stat label="Policy questions answered" value={share(runtime.retrieval.answeredShare)} hint={`${formatInt(runtime.retrieval.count)} asked`} />
      </dl>
      <p>
        <strong>Agent outcomes:</strong> <Counts counts={runtime.agent.byStatus} />
      </p>
      <p>
        <strong>Guardrail findings:</strong> <Counts counts={runtime.agent.guardrailFindings} />
      </p>
      <p>
        <strong>Tool errors:</strong> <Counts counts={runtime.tools.errors} />
      </p>
      {models.length === 0 ? (
        <p className="muted">No language model calls yet.</p>
      ) : (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Model</th>
                <th className="num">Calls</th>
                <th className="num">Failures</th>
                <th className="num">p95</th>
                <th className="num">Input tokens</th>
                <th className="num">Output tokens</th>
                <th className="num">Cost</th>
              </tr>
            </thead>
            <tbody>
              {models.map(([name, m]) => (
                <tr key={name}>
                  <td>{name}</td>
                  <td className="num">{formatInt(m.count)}</td>
                  <td className="num">{formatInt(m.failures)}</td>
                  <td className="num">{ms(m.p95Millis)}</td>
                  <td className="num">{formatInt(m.inputTokens)}</td>
                  <td className="num">{formatInt(m.outputTokens)}</td>
                  <td className="num">
                    {m.estimatedCostUsd === null ? "not priced" : `$${m.estimatedCostUsd.toFixed(4)}`}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <p className="muted">{runtime.costNote}</p>
    </div>
  );
}

function Measured({ value }: { value: string }) {
  return value === NOT_MEASURED ? <Badge tone="warn">{NOT_MEASURED}</Badge> : <>{value}</>;
}

export function QualitySection({ quality }: { quality: AiQuality }) {
  const { forecast, rag, agent } = quality;
  return (
    <div className="stack">
      <Notice tone="info">{quality.note}</Notice>
      <div className="grid-2">
        <div>
          <h3>Forecast</h3>
          {forecast.available ? (
            <dl className="kv">
              <dt>Model</dt>
              <dd>{forecast.modelVersion}</dd>
              <dt>Test MAE vs {forecast.selectedBaseline}</dt>
              <dd>{share(forecast.testMaeImprovementVsBaseline)} better</dd>
              <dt>Actuals inside the forecast range</dt>
              <dd>
                {share(forecast.intervalTestCoverage)} (target {share(forecast.intervalNominalLevel)})
              </dd>
              <dt>Code revision</dt>
              <dd>{forecast.codeRevision ?? "—"}</dd>
            </dl>
          ) : (
            <p className="muted">No forecast evaluation has been stored.</p>
          )}
        </div>
        <div>
          <h3>Document answers</h3>
          {rag.available ? (
            <dl className="kv">
              <dt>Cases</dt>
              <dd>{rag.cases}</dd>
              <dt>Right document found (first / top 3)</dt>
              <dd>
                {share(rag.hitAt1)} / {share(rag.hitAt3)}
              </dd>
              <dt>Answer / citation accuracy</dt>
              <dd>
                {share(rag.answerAccuracy)} / {share(rag.citationAccuracy)}
              </dd>
              <dt>Answers backed by sources</dt>
              <dd>{share(rag.groundedness)}</dd>
              <dt>Restricted-document leaks</dt>
              <dd>{rag.restrictedLeaks}</dd>
              <dt>Language-model generator</dt>
              <dd>
                <Measured value={rag.llmGeneratorMetrics} />
              </dd>
            </dl>
          ) : (
            <p className="muted">No document-answer evaluation has been stored.</p>
          )}
        </div>
        <div>
          <h3>Agent</h3>
          {agent.available ? (
            <dl className="kv">
              <dt>Planner</dt>
              <dd>{agent.planner}</dd>
              <dt>Tasks done correctly</dt>
              <dd>
                {share(agent.workflowSuccess)} on {agent.cases} cases
              </dd>
              <dt>Unseen test cases</dt>
              <dd>{share(agent.holdoutWorkflowSuccess)}</dd>
              <dt>Right tool / right inputs</dt>
              <dd>
                {share(agent.toolCorrectness)} / {share(agent.parameterCorrectness)}
              </dd>
              <dt>Numbers backed by data</dt>
              <dd>{share(agent.groundedNumbers)}</dd>
              <dt>Permissions respected</dt>
              <dd>{share(agent.permissionCompliance)}</dd>
              <dt>Correct refusals</dt>
              <dd>{share(agent.appropriateRefusal)}</dd>
              <dt>Language-model planner</dt>
              <dd>
                <Measured value={agent.llmPlannerMetrics} />
              </dd>
            </dl>
          ) : (
            <p className="muted">No agent evaluation has been stored.</p>
          )}
        </div>
      </div>
    </div>
  );
}

export function Operations() {
  const { user, ready } = useSession();
  const system = useResource(ready ? user.userId : null, (signal) => getOpsSummary(signal));
  const ai = useResource(ready ? user.userId : null, (signal) => getAiTelemetry(signal));
  return (
    <div className="stack">
      <div>
        <h1>Monitoring</h1>
        <p className="lede">How the app and its AI features are doing right now.</p>
      </div>
      <Panel title="System" id="system">
        <ResourceView state={system.state} onRetry={system.reload}>
          {(summary) => <SystemSection summary={summary} />}
        </ResourceView>
      </Panel>
      <Panel title="AI features, live" id="ai-runtime">
        <ResourceView state={ai.state} onRetry={ai.reload}>
          {(data) => <RuntimeSection runtime={data.runtime} />}
        </ResourceView>
      </Panel>
      <Panel title="AI features, last test run" id="ai-quality">
        <ResourceView state={ai.state} onRetry={ai.reload}>
          {(data) => <QualitySection quality={data.quality} />}
        </ResourceView>
      </Panel>
    </div>
  );
}
