package com.scm.platform.approval;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.scm.platform.mlservice.MlEngineClient;
import com.scm.platform.mlservice.MlServiceException;
import com.scm.platform.support.PostgresContainerConfig;
import com.scm.platform.support.TestData;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.dao.DataAccessException;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/** The copilot task -> recommendation -> approval -> decision -> purchase order path, with a stubbed engine. */
@SpringBootTest
@AutoConfigureMockMvc
@Import(PostgresContainerConfig.class)
class AgentApprovalFlowTest {

	private static final String APPROVAL = """
			{"approvalId":"APR-0001","taskId":"TASK-0001","requestedBy":"pat","requesterRole":"planner",
			 "requiredRoles":["procurement_manager"],"approvedRoles":%s,"approvers":%s,"orderValue":1250.0,
			 "status":"%s","createdAt":"2024-12-30T08:00:00Z",
			 "recommendation":{"recommendationId":"REC-PLAN-001","createdAt":"2024-12-30T08:00:00Z",
			   "summary":"Buy 100 widgets from Acme","lines":[{"supplierId":"SUP-1","skuId":"SKU-001",
			   "warehouseId":"W1","quantity":100,"unitPrice":12.5,"shippingCost":40.0}],
			   "objectiveValue":1290.0,"expectedServiceLevel":0.97,"assumptions":["demand x1.2"],
			   "citations":[{"documentId":"POL-1","version":"v2","excerpt":"approval needed"}],
			   "scenarioId":null,"horizonStart":"2024-12-30","horizonEnd":"2025-01-27","status":"%s"}}""";

	@Autowired
	private MockMvc mockMvc;

	@Autowired
	private JdbcClient jdbc;

	@Autowired
	private JsonMapper json;

	@MockitoBean
	private MlEngineClient engine;

	@BeforeEach
	void seed() {
		TestData.seedMasterData(jdbc);
	}

	private JsonNode approval(String status, String recommendationStatus, String approvedRoles, String approvers) {
		return json.readTree(APPROVAL.formatted(approvedRoles, approvers, status, recommendationStatus));
	}

	private static MockHttpServletRequestBuilder as(MockHttpServletRequestBuilder request, String user, String role) {
		return request.header("X-User-Id", user).header("X-User-Role", role);
	}

	private String runTask(String user, String text, String conversationId) throws Exception {
		JsonNode run = json.readTree("""
				{"taskId":"TASK-0001","status":"AWAITING_APPROVAL","answer":"Order is pending approval",
				 "trace":[{"index":0,"kind":"TOOL_CALL","tool":"get_forecast","ok":true}],
				 "recommendationId":"REC-PLAN-001","approvalId":"APR-0001",
				 "citations":[{"documentId":"POL-1"}],"assumptions":["demand x1.2"],"violations":[]}""");
		when(engine.runAgentTask(any(), eq(text))).thenReturn(run);
		when(engine.getApproval("APR-0001")).thenReturn(approval("PENDING", "PENDING_APPROVAL", "[]", "[]"));
		String body = "{\"text\":\"" + text + "\""
				+ (conversationId == null ? "" : ",\"conversationId\":\"" + conversationId + "\"") + "}";
		return mockMvc.perform(as(post("/api/agent/tasks"), user, "planner").contentType(MediaType.APPLICATION_JSON)
						.content(body))
				.andExpect(status().isCreated())
				.andReturn().getResponse().getContentAsString();
	}

	@Test
	void aTaskThatNeedsApprovalStoresTheTaskTheRecommendationAndThePendingApproval() throws Exception {
		String task = runTask("pat", "Demand for SKU-001 will rise 20%", null);

		JsonNode created = json.readTree(task);
		assertThat(created.path("status").asString()).isEqualTo("AWAITING_APPROVAL");
		assertThat(created.path("approvalId").asString()).isEqualTo("APR-0001");
		assertThat(created.path("trace").get(0).path("tool").asString()).isEqualTo("get_forecast");

		mockMvc.perform(as(get("/api/approvals").param("status", "PENDING"), "mia", "procurement_manager"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.length()").value(1))
				.andExpect(jsonPath("$[0].approvalId").value("APR-0001"))
				.andExpect(jsonPath("$[0].requiredRoles[0]").value("procurement_manager"));
		mockMvc.perform(as(get("/api/recommendations/REC-PLAN-001"), "mia", "procurement_manager"))
				.andExpect(jsonPath("$.recommendation.status").value("PENDING_APPROVAL"))
				.andExpect(jsonPath("$.recommendation.assumptions[0]").value("demand x1.2"))
				.andExpect(jsonPath("$.recommendation.citations[0].documentId").value("POL-1"))
				.andExpect(jsonPath("$.lines[0].quantity").value(100))
				.andExpect(jsonPath("$.approval.status").value("PENDING"));
		assertThat(jdbc.sql("SELECT count(*) FROM purchase_order").query(Integer.class).single()).isZero();
	}

	@Test
	void conversationsGroupTasksAndArePrivate() throws Exception {
		String first = runTask("pat", "first question", null);
		String conversationId = json.readTree(first).path("conversationId").asString();
		runTask("pat", "second question", conversationId); // mirrors the same approval again: idempotent

		mockMvc.perform(as(get("/api/agent/conversations/" + conversationId), "pat", "planner"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.tasks.length()").value(2))
				.andExpect(jsonPath("$.tasks[1].requestText").value("second question"));
		assertThat(jdbc.sql("SELECT count(*) FROM approval").query(Integer.class).single()).isEqualTo(1);
		mockMvc.perform(as(get("/api/agent/conversations/" + conversationId), "sam", "planner"))
				.andExpect(status().isNotFound()).andExpect(jsonPath("$.code").value("UNKNOWN_CONVERSATION"));
		mockMvc.perform(as(post("/api/agent/tasks"), "sam", "planner").contentType(MediaType.APPLICATION_JSON)
						.content("{\"text\":\"hi\",\"conversationId\":\"" + conversationId + "\"}"))
				.andExpect(status().isNotFound());
		mockMvc.perform(as(get("/api/agent/conversations"), "pat", "planner"))
				.andExpect(jsonPath("$.length()").value(1));
		mockMvc.perform(as(get("/api/agent/conversations"), "sam", "planner"))
				.andExpect(jsonPath("$.length()").value(0));
	}

	@Test
	void aTaskIsOnlyVisibleToItsOwner() throws Exception {
		String taskId = json.readTree(runTask("pat", "private", null)).path("taskId").asString();
		mockMvc.perform(as(get("/api/agent/tasks/" + taskId), "pat", "planner"))
				.andExpect(status().isOk()).andExpect(jsonPath("$.answer").value("Order is pending approval"));
		mockMvc.perform(as(get("/api/agent/tasks/" + taskId), "sam", "planner")).andExpect(status().isNotFound());
	}

	@Test
	void anApprovedDecisionIsRecordedAndCreatesTheApprovedPurchaseOrder() throws Exception {
		runTask("pat", "Demand for SKU-001 will rise 20%", null);
		when(engine.decideApproval(any(), eq("APR-0001"), eq("APPROVED"), eq("within budget")))
				.thenReturn(approval("APPROVED", "APPROVED", "[\"procurement_manager\"]", "[\"mia\"]"));

		mockMvc.perform(as(post("/api/approvals/APR-0001/decision"), "mia", "procurement_manager")
						.contentType(MediaType.APPLICATION_JSON)
						.content("{\"outcome\":\"APPROVED\",\"rationale\":\"within budget\"}"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.approval.status").value("APPROVED"))
				.andExpect(jsonPath("$.decisions[0].decisionId").value("APR-0001-D001"))
				.andExpect(jsonPath("$.decisions[0].decidedBy").value("mia"))
				.andExpect(jsonPath("$.decisions[0].approverRole").value("procurement_manager"))
				.andExpect(jsonPath("$.recommendation.recommendation.status").value("APPROVED"));

		var orders = jdbc.sql("SELECT po_id, status, quantity, expected_delivery - CURRENT_DATE AS lead_days,"
				+ " recommendation_id FROM purchase_order").query().listOfRows();
		assertThat(orders).hasSize(1);
		assertThat(orders.get(0)).containsEntry("po_id", "APR-0001-PO01").containsEntry("status", "APPROVED")
				.containsEntry("quantity", 100).containsEntry("lead_days", 7)
				.containsEntry("recommendation_id", "REC-PLAN-001");
	}

	@Test
	void aPartialApprovalRecordsTheDecisionButOrdersNothingYet() throws Exception {
		runTask("pat", "Demand for SKU-001 will rise 20%", null);
		when(engine.decideApproval(any(), eq("APR-0001"), eq("APPROVED"), any()))
				.thenReturn(approval("PENDING", "PENDING_APPROVAL", "[\"procurement_manager\"]", "[\"mia\"]"));

		mockMvc.perform(as(post("/api/approvals/APR-0001/decision"), "mia", "procurement_manager")
						.contentType(MediaType.APPLICATION_JSON).content("{\"outcome\":\"APPROVED\"}"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.approval.status").value("PENDING"))
				.andExpect(jsonPath("$.approval.approvedRoles[0]").value("procurement_manager"));
		assertThat(jdbc.sql("SELECT count(*) FROM purchase_order").query(Integer.class).single()).isZero();
	}

	@Test
	void aRejectionIsRecordedAndOrdersNothing() throws Exception {
		runTask("pat", "Demand for SKU-001 will rise 20%", null);
		when(engine.decideApproval(any(), eq("APR-0001"), eq("REJECTED"), any()))
				.thenReturn(approval("REJECTED", "REJECTED", "[]", "[]"));

		mockMvc.perform(as(post("/api/approvals/APR-0001/decision"), "mia", "procurement_manager")
						.contentType(MediaType.APPLICATION_JSON)
						.content("{\"outcome\":\"REJECTED\",\"rationale\":\"too costly\"}"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.approval.status").value("REJECTED"))
				.andExpect(jsonPath("$.decisions[0].outcome").value("REJECTED"));
		assertThat(jdbc.sql("SELECT count(*) FROM purchase_order").query(Integer.class).single()).isZero();
		mockMvc.perform(as(get("/api/recommendations").param("status", "REJECTED"), "mia", "procurement_manager"))
				.andExpect(jsonPath("$.length()").value(1));
	}

	@Test
	void anEngineRefusalIsRelayedAndNothingIsStored() throws Exception {
		runTask("pat", "Demand for SKU-001 will rise 20%", null);
		when(engine.decideApproval(any(), eq("APR-0001"), any(), any()))
				.thenThrow(new MlServiceException(403, "NOT_AUTHORIZED", "role planner cannot decide this approval"));

		mockMvc.perform(as(post("/api/approvals/APR-0001/decision"), "pat", "planner")
						.contentType(MediaType.APPLICATION_JSON).content("{\"outcome\":\"APPROVED\"}"))
				.andExpect(status().isForbidden())
				.andExpect(jsonPath("$.code").value("NOT_AUTHORIZED"));
		assertThat(jdbc.sql("SELECT count(*) FROM decision").query(Integer.class).single()).isZero();
		mockMvc.perform(as(get("/api/approvals/APR-0001"), "pat", "planner"))
				.andExpect(jsonPath("$.approval.status").value("PENDING"));
	}

	@Test
	void decisionsCannotBeAlteredOrRemoved() throws Exception {
		runTask("pat", "Demand for SKU-001 will rise 20%", null);
		when(engine.decideApproval(any(), eq("APR-0001"), any(), any()))
				.thenReturn(approval("REJECTED", "REJECTED", "[]", "[]"));
		mockMvc.perform(as(post("/api/approvals/APR-0001/decision"), "mia", "procurement_manager")
				.contentType(MediaType.APPLICATION_JSON).content("{\"outcome\":\"REJECTED\"}"));

		org.assertj.core.api.Assertions
				.assertThatThrownBy(() -> jdbc.sql("UPDATE decision SET outcome = 'APPROVED'").update())
				.isInstanceOf(DataAccessException.class).hasMessageContaining("append-only");
		org.assertj.core.api.Assertions.assertThatThrownBy(() -> jdbc.sql("DELETE FROM decision").update())
				.isInstanceOf(DataAccessException.class);
	}

	@Test
	void invalidRequestsAreRejectedBeforeReachingTheEngine() throws Exception {
		mockMvc.perform(as(post("/api/approvals/APR-0001/decision"), "mia", "procurement_manager")
						.contentType(MediaType.APPLICATION_JSON).content("{\"outcome\":\"MAYBE\"}"))
				.andExpect(status().isBadRequest());
		mockMvc.perform(as(post("/api/agent/tasks"), "pat", "planner").contentType(MediaType.APPLICATION_JSON)
						.content("{\"text\":\"  \"}"))
				.andExpect(status().isBadRequest()).andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));
		mockMvc.perform(as(get("/api/approvals").param("status", "WAITING"), "mia", "procurement_manager"))
				.andExpect(status().isBadRequest()).andExpect(jsonPath("$.code").value("INVALID_STATUS"));
		mockMvc.perform(as(get("/api/approvals/APR-9999"), "mia", "procurement_manager"))
				.andExpect(status().isNotFound()).andExpect(jsonPath("$.code").value("UNKNOWN_APPROVAL"));
		mockMvc.perform(as(get("/api/recommendations/REC-NOPE"), "mia", "procurement_manager"))
				.andExpect(status().isNotFound()).andExpect(jsonPath("$.code").value("UNKNOWN_RECOMMENDATION"));
	}

}
