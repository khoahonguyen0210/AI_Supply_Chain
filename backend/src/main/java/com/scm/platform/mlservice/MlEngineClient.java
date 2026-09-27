package com.scm.platform.mlservice;

import com.scm.platform.security.Actor;
import tools.jackson.databind.JsonNode;

public interface MlEngineClient {

	JsonNode searchSuppliers(Actor actor, JsonNode request);

	JsonNode supplierPerformance(Actor actor, String supplierId);

	JsonNode optimize(Actor actor, JsonNode request);

	JsonNode runScenario(Actor actor, JsonNode request);

	JsonNode askDocuments(Actor actor, JsonNode request);

	JsonNode runAgentTask(Actor actor, String text);

	JsonNode getAgentTask(String taskId);

	JsonNode listApprovals(String status);

	JsonNode telemetry();

	JsonNode getApproval(String approvalId);

	JsonNode decideApproval(Actor approver, String approvalId, String outcome, String rationale);

	JsonNode forecastSnapshot(Actor actor, JsonNode request);

	JsonNode evaluateOutcomes(Actor actor, JsonNode request);

}
