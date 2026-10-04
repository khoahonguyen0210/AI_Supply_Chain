
export interface FieldViolation {
  field: string;
  message: string;
}

export interface ApiErrorBody {
  timestamp: string;
  status: number;
  code: string;
  message: string;
  path: string;
  violations: FieldViolation[];
}

export interface HealthResponse {
  status: string;
  service: string;
  version: string;
  timestamp: string;
}


export interface Region {
  regionId: string;
  name: string;
}

export interface Sku {
  skuId: string;
  name: string;
  category: string;
  unitPrice: number;
  unitVolume: number;
  requiredCertifications: string[];
}

export interface Supplier {
  supplierId: string;
  name: string;
  regionId: string;
  reliability: number;
  qualityScore: number;
  certifications: string[];
}

export interface Contract {
  contractId: string;
  status: string;
  effectiveFrom: string;
  effectiveTo: string;
  paymentTermsDays: number;
  maxOrderValue: number | null;
}

export interface Offer {
  offerId: string;
  skuId: string;
  unitPrice: number;
  moq: number;
  capacityPerWeek: number;
  leadTimeDays: number;
  validFrom: string;
  validTo: string;
}

export interface SupplierDetail {
  supplier: Supplier;
  contracts: Contract[];
  offers: Offer[];
}

export interface DemandPoint {
  skuId: string;
  regionId: string;
  periodStart: string;
  quantity: number;
}

export interface InventoryRow {
  skuId: string;
  warehouseId: string;
  asOf: string;
  onHand: number;
  incoming: number;
  safetyStock: number;
}


export interface ForecastPoint {
  weekStart: string;
  horizon: number;
  point: number;
  lower: number;
  upper: number;
}

export interface ForecastResponse {
  schemaVersion: string;
  modelVersion: string;
  datasetId: string;
  skuId: string;
  regionId: string;
  asOf: string;
  intervalLevel: number;
  method: string;
  points: ForecastPoint[];
}


export type JobType = "FORECAST" | "OPTIMIZATION" | "SCENARIO" | "BATCH_EVALUATION";
export type JobStatus = "QUEUED" | "RUNNING" | "SUCCEEDED" | "FAILED";

export interface Job<R = unknown> {
  id: string;
  type: JobType;
  status: JobStatus;
  attempts: number;
  maxAttempts: number;
  result: R | null;
  errorCode: string | null;
  errorMessage: string | null;
  lastError: string | null;
  createdAt: string;
  startedAt: string | null;
  finishedAt: string | null;
}


export interface PlanSpec {
  skuIds: string[];
  horizonWeeks: number;
  demandMultiplier: number;
  budget?: number;
  serviceLevel: number;
}

export interface PlanViolation {
  kind: string;
  subject: string;
  amount: number;
}

export interface PlanLine {
  supplierId: string;
  skuId: string;
  warehouseId: string;
  quantity: number;
  unitPrice: number;
  value: number;
}

export interface PlanResult {
  planId: string;
  skuIds: string[];
  horizonWeeks: number;
  demandMultiplier: number;
  serviceLevelTarget: number;
  budget: number | null;
  solverStatus: string;
  objective: number;
  spend: number;
  orderValue: number;
  totalDemand: number;
  fillRate: number;
  unmetDemand: number;
  orders: number;
  unitsOrdered: number;
  customerFillRate: number;
  violations: PlanViolation[];
  bySupplier: { supplierId: string; units: number; spend: number }[];
  lines: PlanLine[];
  bindingConstraints: { kind: string; subject: string; utilization: number }[];
}

export interface ScenarioComparison {
  planId: string;
  scenarioType: string;
  parameters: Record<string, number | string>;
  assumptionsChanged: string[];
  baselineObjective: number;
  disruptedObjectiveDelta: number;
  responseObjectiveDelta: number;
  resilienceCost: number;
  responseBenefit: number;
  serviceDeltaDisrupted: number;
  serviceDeltaResponse: number;
  baselineCustomerFillRate: number;
  responseCustomerFillRate: number;
  newlyBinding: string[];
  changedPurchaseLines: number;
  supplierShifts: { supplierId: string; baselineUnits: number; responseUnits: number }[];
}

export interface ScenarioRunResult {
  plan: PlanResult;
  scenario: ScenarioComparison;
}

export interface RankedSupplier {
  rank: number;
  supplierId: string;
  supplierName: string;
  landedUnitCost: number;
  totalCost: number;
  costVsCheapestPct: number;
  leadTimeDays: number;
  reliability: number;
  qualityScore: number;
}

export interface SupplierSearchResult {
  skuId: string;
  warehouseId: string;
  quantity: number;
  maxLeadTimeDays: number;
  eligibleCount: number;
  ranked: RankedSupplier[];
  rejected: Record<string, string[]>;
  cheapestOverall: {
    supplierId: string;
    landedUnitCost: number;
    eligible: boolean;
    rejectionReasons: string[];
  } | null;
  tradeOffs: string[];
}

export interface SupplierSearchRequest {
  skuId: string;
  warehouseId: string;
  quantity: number;
  maxLeadTimeDays?: number;
  horizonWeeks?: number;
}

export interface PolicyCitation {
  documentId: string;
  version: string;
  status?: string;
  excerpt: string;
}

export interface DocumentAnswer {
  question: string;
  status: string;
  answer: string;
  citations: PolicyCitation[];
}


export interface DocumentSummary {
  documentId: string;
  version: string;
  docType: string;
  title: string;
  effectiveDate: string;
  expiryDate: string | null;
  supplierId: string | null;
  inForce: boolean;
}

export interface DocumentDetail {
  summary: DocumentSummary;
  allowedRoles: string[];
  content: string;
}


export type ScenarioType =
  | "DEMAND_SHOCK"
  | "SUPPLIER_OUTAGE"
  | "PRICE_SHOCK"
  | "CAPACITY_REDUCTION"
  | "LEAD_TIME_SHOCK"
  | "WAREHOUSE_CAPACITY_REDUCTION"
  | "TRANSPORT_COST_SHOCK";

export interface ScenarioDefinition {
  scenarioId: string;
  name: string;
  scenarioType: ScenarioType;
  parameters: Record<string, number | string>;
  createdAt: string;
}


export type ApprovalStatus = "PENDING" | "APPROVED" | "REJECTED";
export type RecommendationStatus = "PROPOSED" | "PENDING_APPROVAL" | "APPROVED" | "REJECTED";

export interface Recommendation {
  recommendationId: string;
  createdAt: string;
  summary: string;
  objectiveValue: number;
  expectedServiceLevel: number;
  assumptions: string[];
  citations: PolicyCitation[];
  horizonStart: string;
  horizonEnd: string;
  status: RecommendationStatus;
}

export interface RecommendationLine {
  lineNo: number;
  supplierId: string;
  skuId: string;
  warehouseId: string;
  quantity: number;
  unitPrice: number;
  shippingCost: number;
}

export interface Approval {
  approvalId: string;
  recommendationId: string;
  requestedBy: string;
  requesterRole: string;
  requiredRoles: string[];
  approvedRoles: string[];
  approvers: string[];
  orderValue: number;
  status: ApprovalStatus;
  createdAt: string;
  updatedAt: string;
}

export interface Decision {
  decisionId: string;
  decidedBy: string;
  approverRole: string;
  outcome: "APPROVED" | "REJECTED";
  decidedAt: string;
  rationale: string | null;
}

export interface RecommendationDetail {
  recommendation: Recommendation;
  lines: RecommendationLine[];
  approval: Approval | null;
  decisions: Decision[];
}

export interface ApprovalDetail {
  approval: Approval;
  recommendation: RecommendationDetail;
  decisions: Decision[];
}


export type AgentStatus =
  | "COMPLETED"
  | "AWAITING_APPROVAL"
  | "REFUSED"
  | "NEEDS_CLARIFICATION"
  | "FAILED";

export interface TraceStep {
  index: number;
  kind: "TOOL_CALL" | "FINAL" | "REFUSAL" | "CLARIFICATION";
  tool: string | null;
  arguments: Record<string, unknown>;
  reason: string;
  replan: boolean;
  ok: boolean;
  errorCode: string | null;
  summary: string;
}

export interface AgentTask {
  taskId: string;
  conversationId: string;
  engineTaskId: string;
  requestText: string;
  status: AgentStatus;
  answer: string;
  trace: TraceStep[];
  citations: PolicyCitation[];
  assumptions: string[];
  violations: string[];
  recommendationId: string | null;
  approvalId: string | null;
  createdAt: string;
}

export interface Conversation {
  conversationId: string;
  userId: string;
  createdAt: string;
}

export interface ConversationView {
  conversation: Conversation;
  tasks: AgentTask[];
}


export interface OpsSummary {
  api: {
    requests: number;
    serverErrors: number;
    clientErrors: number;
    errorRate: number;
    p50Millis: number;
    p95Millis: number;
    requestsPerSecond: number;
    uptimeSeconds: number;
  };
  queue: {
    byStatus: Record<JobStatus, number>;
    oldestQueuedSeconds: number;
    workerUtilization: number;
    meanDurationMillis: Record<string, number>;
    failedAttempts: Record<string, number>;
  };
}

export interface SeriesStats {
  count: number;
  failures: number;
  failureRate: number;
  meanMillis: number;
  p50Millis: number;
  p95Millis: number;
}

export interface AiRuntime {
  uptimeSeconds: number;
  forecast: SeriesStats;
  tools: {
    calls: number;
    successRate: number | null;
    byTool: Record<string, SeriesStats>;
    errors: Record<string, number>;
  };
  agent: SeriesStats & {
    byStatus: Record<string, number>;
    guardrailFindings: Record<string, number>;
  };
  retrieval: SeriesStats & { byStatus: Record<string, number>; answeredShare: number | null };
  models: Record<
    string,
    SeriesStats & { inputTokens: number; outputTokens: number; estimatedCostUsd: number | null }
  >;
  costNote: string;
}

export type Unavailable = { available: false };

export interface AiQuality {
  note: string;
  forecast:
    | Unavailable
    | {
        available: true;
        modelVersion: string | null;
        selectedBaseline: string | null;
        testMaeImprovementVsBaseline: number | null;
        testMae: number | null;
        testWape: number | null;
        intervalNominalLevel: number | null;
        intervalTestCoverage: number | null;
        codeRevision: string | null;
      };
  rag:
    | Unavailable
    | {
        available: true;
        cases: number | null;
        embedder: string | null;
        generator: string | null;
        hitAt1: number | null;
        hitAt3: number | null;
        mrr: number | null;
        answerAccuracy: number | null;
        citationAccuracy: number | null;
        groundedness: number | null;
        restrictedLeaks: number | null;
        llmGeneratorMetrics: string;
        codeRevision: string | null;
      };
  agent:
    | Unavailable
    | {
        available: true;
        planner: string | null;
        cases: number | null;
        workflowSuccess: number | null;
        holdoutWorkflowSuccess: number | null;
        toolCorrectness: number | null;
        parameterCorrectness: number | null;
        groundedNumbers: number | null;
        permissionCompliance: number | null;
        appropriateRefusal: number | null;
        llmPlannerMetrics: string;
        codeRevision: string | null;
      };
}

export interface AiTelemetry {
  runtime: AiRuntime;
  quality: AiQuality;
}
