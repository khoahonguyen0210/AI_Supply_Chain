package com.scm.platform.mlservice;

import com.scm.platform.security.Actor;
import java.util.LinkedHashMap;
import java.util.Map;
import java.util.Optional;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.node.ObjectNode;

public class PythonEngineClient implements MlEngineClient {

	static final String SCHEMA_VERSION = "1";

	private static final String CONTRACT = "engine schema version " + SCHEMA_VERSION;

	private final RestClient restClient;

	public PythonEngineClient(RestClient restClient) {
		this.restClient = restClient;
	}

	@Override
	public JsonNode searchSuppliers(Actor actor, JsonNode request) {
		return post("/v1/suppliers/search", envelope(actor, request));
	}

	@Override
	public JsonNode supplierPerformance(Actor actor, String supplierId) {
		Map<String, Object> body = base(actor);
		body.put("supplierId", supplierId);
		return post("/v1/suppliers/performance", body);
	}

	@Override
	public JsonNode optimize(Actor actor, JsonNode request) {
		return post("/v1/plans/optimize", envelope(actor, request));
	}

	@Override
	public JsonNode runScenario(Actor actor, JsonNode request) {
		return post("/v1/scenarios/run", envelope(actor, request));
	}

	@Override
	public JsonNode askDocuments(Actor actor, JsonNode request) {
		return post("/v1/documents/ask", envelope(actor, request));
	}

	@Override
	public JsonNode runAgentTask(Actor actor, String text) {
		Map<String, Object> body = base(actor);
		body.put("text", text);
		return post("/v1/agent/tasks", body);
	}

	@Override
	public JsonNode getAgentTask(String taskId) {
		return unwrap(MlErrors.call(CONTRACT,
				() -> restClient.get().uri("/v1/agent/tasks/{id}", taskId).retrieve().body(JsonNode.class)));
	}

	@Override
	public JsonNode listApprovals(String status) {
		return unwrap(MlErrors.call(CONTRACT, () -> restClient.get()
				.uri(uri -> uri.path("/v1/approvals").queryParamIfPresent("status", Optional.ofNullable(status))
						.build())
				.retrieve().body(JsonNode.class)));
	}

	@Override
	public JsonNode telemetry() {
		JsonNode body = MlErrors.call(CONTRACT,
				() -> restClient.get().uri("/v1/telemetry").retrieve().body(JsonNode.class));
		if (body == null || !body.has("runtime") || !body.has("quality")) {
			throw MlErrors.contractMismatch(CONTRACT);
		}
		return body;
	}

	@Override
	public JsonNode getApproval(String approvalId) {
		return unwrap(MlErrors.call(CONTRACT,
				() -> restClient.get().uri("/v1/approvals/{id}", approvalId).retrieve().body(JsonNode.class)));
	}

	@Override
	public JsonNode decideApproval(Actor approver, String approvalId, String outcome, String rationale) {
		Map<String, Object> body = base(approver);
		body.put("outcome", outcome);
		if (rationale != null) {
			body.put("rationale", rationale);
		}
		return post("/v1/approvals/" + approvalId + "/decision", body);
	}

	private JsonNode post(String path, Object body) {
		return unwrap(MlErrors.call(CONTRACT,
				() -> restClient.post().uri(path).body(body).retrieve().body(JsonNode.class)));
	}

	private static Map<String, Object> base(Actor actor) {
		Map<String, Object> body = new LinkedHashMap<>();
		body.put("schemaVersion", SCHEMA_VERSION);
		body.put("actor", Map.of("userId", actor.userId(), "role", actor.role()));
		return body;
	}

	private static ObjectNode envelope(Actor actor, JsonNode request) {
		if (!(request instanceof ObjectNode fields)) {
			throw new IllegalArgumentException("engine requests must be JSON objects");
		}
		ObjectNode body = fields.deepCopy();
		body.put("schemaVersion", SCHEMA_VERSION);
		ObjectNode who = body.putObject("actor");
		who.put("userId", actor.userId());
		who.put("role", actor.role());
		return body;
	}

	private static JsonNode unwrap(JsonNode response) {
		if (response == null || response.get("data") == null
				|| !SCHEMA_VERSION.equals(response.path("schemaVersion").asString(""))) {
			throw MlErrors.contractMismatch(CONTRACT);
		}
		return response.get("data");
	}

}
