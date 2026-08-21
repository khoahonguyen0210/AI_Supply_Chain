package com.scm.platform.mlservice;

import com.scm.platform.security.Actor;
import tools.jackson.databind.JsonNode;

/**
 * Backend boundary to the Python planning engine (docs/contracts/engine-api.md).
 *
 * <p>Requests are relayed as JSON together with the acting user; the {@code data} of the response
 * is returned untouched. The engine owns every planning rule, so nothing here interprets results.
 */
public interface MlEngineClient {

	JsonNode searchSuppliers(Actor actor, JsonNode request);

	JsonNode supplierPerformance(Actor actor, String supplierId);

	JsonNode optimize(Actor actor, JsonNode request);

	JsonNode runScenario(Actor actor, JsonNode request);

	JsonNode askDocuments(Actor actor, JsonNode request);

	JsonNode runAgentTask(Actor actor, String text);

	JsonNode getAgentTask(String taskId);

	JsonNode listApprovals(String status);

	/** Runtime telemetry and offline-evaluation headlines (not wrapped in the v1 envelope). */
	JsonNode telemetry();

	JsonNode getApproval(String approvalId);

	JsonNode decideApproval(Actor approver, String approvalId, String outcome, String rationale);

}
