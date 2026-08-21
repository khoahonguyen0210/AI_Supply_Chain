package com.scm.platform.mlservice;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.jsonPath;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.queryParam;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

import com.scm.platform.security.Actor;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/** The engine client sends v1 requests carrying the actor and returns only the response's {@code data}. */
class PythonEngineClientTest {

	private static final Actor ACTOR = new Actor("pat", "planner");

	private final JsonMapper json = JsonMapper.builder().build();

	private MockRestServiceServer server;

	private PythonEngineClient client;

	@BeforeEach
	void setUp() {
		RestClient.Builder builder = RestClient.builder().baseUrl("http://ml.test");
		server = MockRestServiceServer.bindTo(builder).build();
		client = new PythonEngineClient(builder.build());
	}

	private static String envelope(String data) {
		return "{\"schemaVersion\":\"1\",\"data\":" + data + "}";
	}

	@Test
	void relaysARequestWithTheSchemaVersionAndTheActor() {
		server.expect(requestTo("http://ml.test/v1/plans/optimize"))
				.andExpect(method(HttpMethod.POST))
				.andExpect(jsonPath("$.schemaVersion").value("1"))
				.andExpect(jsonPath("$.actor.userId").value("pat"))
				.andExpect(jsonPath("$.actor.role").value("planner"))
				.andExpect(jsonPath("$.skuIds[0]").value("SKU-001"))
				.andRespond(withSuccess(envelope("{\"planId\":\"PLAN-1\"}"), MediaType.APPLICATION_JSON));

		JsonNode data = client.optimize(ACTOR, json.readTree("{\"skuIds\":[\"SKU-001\"]}"));

		assertThat(data.path("planId").asString()).isEqualTo("PLAN-1");
		server.verify();
	}

	@Test
	void agentTasksAndDecisionsCarryTheirOwnFields() {
		server.expect(requestTo("http://ml.test/v1/agent/tasks"))
				.andExpect(jsonPath("$.text").value("forecast SKU-001"))
				.andExpect(jsonPath("$.actor.role").value("planner"))
				.andRespond(withSuccess(envelope("{\"taskId\":\"TASK-1\"}"), MediaType.APPLICATION_JSON));
		server.expect(requestTo("http://ml.test/v1/approvals/APR-1/decision"))
				.andExpect(jsonPath("$.outcome").value("APPROVED"))
				.andExpect(jsonPath("$.rationale").value("ok"))
				.andExpect(jsonPath("$.actor.userId").value("mia"))
				.andRespond(withSuccess(envelope("{\"status\":\"APPROVED\"}"), MediaType.APPLICATION_JSON));

		assertThat(client.runAgentTask(ACTOR, "forecast SKU-001").path("taskId").asString()).isEqualTo("TASK-1");
		assertThat(client.decideApproval(new Actor("mia", "procurement_manager"), "APR-1", "APPROVED", "ok")
				.path("status").asString()).isEqualTo("APPROVED");
		server.verify();
	}

	@Test
	void readsUseGetWithOptionalFilters() {
		server.expect(requestTo("http://ml.test/v1/approvals?status=PENDING")).andExpect(method(HttpMethod.GET))
				.andExpect(queryParam("status", "PENDING"))
				.andRespond(withSuccess(envelope("{\"approvals\":[]}"), MediaType.APPLICATION_JSON));
		server.expect(requestTo("http://ml.test/v1/approvals")).andExpect(method(HttpMethod.GET))
				.andRespond(withSuccess(envelope("{\"approvals\":[1]}"), MediaType.APPLICATION_JSON));
		server.expect(requestTo("http://ml.test/v1/agent/tasks/TASK-1"))
				.andRespond(withSuccess(envelope("{\"taskId\":\"TASK-1\"}"), MediaType.APPLICATION_JSON));
		server.expect(requestTo("http://ml.test/v1/approvals/APR-1"))
				.andRespond(withSuccess(envelope("{\"approvalId\":\"APR-1\"}"), MediaType.APPLICATION_JSON));

		assertThat(client.listApprovals("PENDING").path("approvals")).isEmpty();
		assertThat(client.listApprovals(null).path("approvals")).hasSize(1);
		assertThat(client.getAgentTask("TASK-1").path("taskId").asString()).isEqualTo("TASK-1");
		assertThat(client.getApproval("APR-1").path("approvalId").asString()).isEqualTo("APR-1");
		server.verify();
	}

	@Test
	void engineErrorsKeepTheirStatusAndCode() {
		server.expect(requestTo("http://ml.test/v1/suppliers/search"))
				.andRespond(withStatus(HttpStatus.NOT_FOUND).contentType(MediaType.APPLICATION_JSON)
						.body("{\"code\":\"UNKNOWN_WAREHOUSE\",\"message\":\"unknown warehouse NOPE\"}"));

		assertThatThrownBy(() -> client.searchSuppliers(ACTOR, json.readTree("{}")))
				.isInstanceOfSatisfying(MlServiceException.class, ex -> {
					assertThat(ex.status()).isEqualTo(404);
					assertThat(ex.code()).isEqualTo("UNKNOWN_WAREHOUSE");
				});
	}

	@Test
	void aResponseWithoutTheV1EnvelopeIsAContractMismatch() {
		server.expect(requestTo("http://ml.test/v1/documents/ask"))
				.andRespond(withSuccess("{\"schemaVersion\":\"2\",\"data\":{}}", MediaType.APPLICATION_JSON));
		server.expect(requestTo("http://ml.test/v1/documents/ask"))
				.andRespond(withSuccess("{\"unexpected\":true}", MediaType.APPLICATION_JSON));

		for (int i = 0; i < 2; i++) {
			assertThatThrownBy(() -> client.askDocuments(ACTOR, json.readTree("{}")))
					.isInstanceOfSatisfying(MlServiceException.class, ex -> {
						assertThat(ex.status()).isEqualTo(502);
						assertThat(ex.code()).isEqualTo("ML_CONTRACT_MISMATCH");
					});
		}
	}

	@Test
	void anErrorBodyOutsideTheContractBecomesAGenericBadGateway() {
		server.expect(requestTo("http://ml.test/v1/scenarios/run"))
				.andRespond(withStatus(HttpStatus.INTERNAL_SERVER_ERROR).body("<html>oops</html>"));

		assertThatThrownBy(() -> client.runScenario(ACTOR, json.readTree("{}")))
				.isInstanceOfSatisfying(MlServiceException.class, ex -> assertThat(ex.code())
						.isEqualTo("ML_SERVICE_ERROR"));
	}

	@Test
	void telemetryIsReadWithoutTheEnvelopeAndMustHaveBothSections() {
		server.expect(requestTo("http://ml.test/v1/telemetry")).andExpect(method(HttpMethod.GET))
				.andRespond(withSuccess("{\"runtime\":{},\"quality\":{}}", MediaType.APPLICATION_JSON));
		server.expect(requestTo("http://ml.test/v1/telemetry"))
				.andRespond(withSuccess("{\"runtime\":{}}", MediaType.APPLICATION_JSON));

		assertThat(client.telemetry().has("quality")).isTrue();
		assertThatThrownBy(() -> client.telemetry()).isInstanceOfSatisfying(MlServiceException.class,
				ex -> assertThat(ex.code()).isEqualTo("ML_CONTRACT_MISMATCH"));
	}

	@Test
	void requestsMustBeJsonObjects() {
		assertThatThrownBy(() -> client.optimize(ACTOR, json.readTree("[1]")))
				.isInstanceOf(IllegalArgumentException.class);
	}

}
