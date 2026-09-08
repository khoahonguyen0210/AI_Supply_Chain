import { apiGet, apiPost, query } from "./client";
import type {
  AgentTask,
  AiTelemetry,
  Approval,
  ApprovalDetail,
  ApprovalStatus,
  Conversation,
  ConversationView,
  DocumentAnswer,
  DocumentDetail,
  DocumentSummary,
  Job,
  OpsSummary,
  PlanSpec,
  Recommendation,
  RecommendationDetail,
  RecommendationStatus,
  ScenarioDefinition,
  ScenarioType,
} from "./types";

export const listRecommendations = (status?: RecommendationStatus, signal?: AbortSignal) =>
  apiGet<Recommendation[]>(`/api/recommendations${query({ status })}`, signal);

export const getRecommendation = (id: string, signal?: AbortSignal) =>
  apiGet<RecommendationDetail>(`/api/recommendations/${encodeURIComponent(id)}`, signal);

export const listApprovals = (status?: ApprovalStatus, signal?: AbortSignal) =>
  apiGet<Approval[]>(`/api/approvals${query({ status })}`, signal);

export const getApproval = (id: string, signal?: AbortSignal) =>
  apiGet<ApprovalDetail>(`/api/approvals/${encodeURIComponent(id)}`, signal);

export const decideApproval = (
  id: string,
  outcome: "APPROVED" | "REJECTED",
  rationale?: string,
) =>
  apiPost<ApprovalDetail>(`/api/approvals/${encodeURIComponent(id)}/decision`, {
    outcome,
    rationale: rationale || undefined,
  });

export const listScenarios = (signal?: AbortSignal) =>
  apiGet<ScenarioDefinition[]>("/api/scenarios", signal);

export const createScenario = (
  name: string,
  scenarioType: ScenarioType,
  parameters: Record<string, number | string>,
) => apiPost<ScenarioDefinition>("/api/scenarios", { name, scenarioType, parameters });

export const runScenario = (scenarioId: string, plan: PlanSpec, idempotencyKey?: string) =>
  apiPost<Job>(
    `/api/scenarios/${encodeURIComponent(scenarioId)}/runs`,
    { plan },
    { idempotencyKey },
  );

export const listDocuments = (
  filters: { docType?: string; supplierId?: string; asOf?: string; includeSuperseded?: boolean },
  signal?: AbortSignal,
) => apiGet<DocumentSummary[]>(`/api/documents${query(filters)}`, signal);

export const getDocument = (
  documentId: string,
  filters: { version?: string; asOf?: string } = {},
  signal?: AbortSignal,
) =>
  apiGet<DocumentDetail>(
    `/api/documents/${encodeURIComponent(documentId)}${query(filters)}`,
    signal,
  );

export const askDocuments = (question: string) =>
  apiPost<DocumentAnswer>("/api/documents/ask", { question });

export const runAgentTask = (text: string, conversationId?: string) =>
  apiPost<AgentTask>("/api/agent/tasks", { text, conversationId });

export const listConversations = (signal?: AbortSignal) =>
  apiGet<Conversation[]>("/api/agent/conversations", signal);

export const getConversation = (id: string, signal?: AbortSignal) =>
  apiGet<ConversationView>(`/api/agent/conversations/${encodeURIComponent(id)}`, signal);

export const getOpsSummary = (signal?: AbortSignal) => apiGet<OpsSummary>("/api/ops/summary", signal);

export const getAiTelemetry = (signal?: AbortSignal) => apiGet<AiTelemetry>("/api/ops/ai", signal);
