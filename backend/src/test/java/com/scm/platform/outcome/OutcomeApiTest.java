package com.scm.platform.outcome;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.scm.platform.mlservice.MlEngineClient;
import com.scm.platform.support.PostgresContainerConfig;
import com.scm.platform.support.TestAuth;
import com.scm.platform.support.TestData;
import java.util.Map;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.mockito.ArgumentCaptor;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.dao.DataAccessException;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.ResultActions;
import org.springframework.test.web.servlet.request.MockMvcRequestBuilders;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

@SpringBootTest
@AutoConfigureMockMvc
@Import(PostgresContainerConfig.class)
class OutcomeApiTest {

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
		jdbc.sql("""
				INSERT INTO recommendation (recommendation_id, created_at, summary, objective_value,
				    expected_service_level, horizon_start, horizon_end, status)
				VALUES ('REC-1', '2024-12-30T08:00:00Z', 'Buy widgets', 1290, 0.97, '2024-12-30', '2025-01-27',
				    'APPROVED')""").update();
		jdbc.sql("INSERT INTO recommendation_line VALUES ('REC-1', 1, 'SUP-1', 'SKU-001', 'W1', 100, 12.5, 40)")
				.update();
		jdbc.sql("""
				INSERT INTO purchase_order (po_id, supplier_id, sku_id, warehouse_id, quantity, unit_price, status,
				    created_at, expected_delivery, recommendation_id) VALUES
				('APR-1-PO01', 'SUP-1', 'SKU-001', 'W1', 100, 12.5, 'APPROVED', '2024-12-30T09:00:00Z',
				    '2025-01-06', 'REC-1'),
				('PO-REJ', 'SUP-1', 'SKU-001', 'W1', 10, 12.5, 'REJECTED', '2024-12-30T09:00:00Z', '2025-01-06',
				    NULL)""").update();
	}

	private ResultActions post(String path, String user, String role, String body) throws Exception {
		return mockMvc.perform(TestAuth.as(MockMvcRequestBuilders.post(path), user, role)
				.contentType(MediaType.APPLICATION_JSON).content(body));
	}

	private Map<String, Object> lastAudit(String user) {
		return jdbc.sql("SELECT action, outcome, status, actor_role FROM audit_log WHERE actor_user = :u"
				+ " ORDER BY audit_id DESC LIMIT 1").param("u", user).query().singleRow();
	}

	@Test
	void aDeliveryIsRecordedAppendOnlyMovesTheOrderToDeliveredAndIsAudited() throws Exception {
		post("/api/outcomes/deliveries", "mia", "procurement_manager",
				"{\"poId\":\"APR-1-PO01\",\"deliveredOn\":\"2025-01-09\",\"deliveredQuantity\":90}")
				.andExpect(status().isCreated())
				.andExpect(jsonPath("$.status").value("DELIVERED"));

		Map<String, Object> order = jdbc.sql("SELECT status, delivered_at::text AS on_date, delivered_quantity"
				+ " FROM purchase_order WHERE po_id = 'APR-1-PO01'").query().singleRow();
		assertThat(order).containsEntry("status", "DELIVERED").containsEntry("on_date", "2025-01-09")
				.containsEntry("delivered_quantity", 90);
		Map<String, Object> outcome = jdbc.sql("SELECT source, recorded_by FROM outcome_delivery").query()
				.singleRow();
		assertThat(outcome).containsEntry("source", "RECORDED").containsEntry("recorded_by", "mia");
		assertThat(lastAudit("mia")).containsEntry("action", "POST /api/outcomes/deliveries")
				.containsEntry("outcome", "SUCCESS");
		assertThatThrownBy(() -> jdbc.sql("UPDATE outcome_delivery SET delivered_quantity = 100").update())
				.isInstanceOf(DataAccessException.class).hasMessageContaining("append-only");
	}

	@Test
	void financeMayReadTheEvaluationButNotRecordOutcomesAndTheRefusalIsAudited() throws Exception {
		post("/api/outcomes/demand", "fay", "finance",
				"{\"records\":[{\"skuId\":\"SKU-001\",\"regionId\":\"R1\",\"weekStart\":\"2024-12-30\","
						+ "\"quantity\":5}]}")
				.andExpect(status().isForbidden());
		post("/api/outcomes/deliveries", "fay", "finance",
				"{\"poId\":\"APR-1-PO01\",\"deliveredOn\":\"2025-01-09\",\"deliveredQuantity\":90}")
				.andExpect(status().isForbidden());

		assertThat(lastAudit("fay")).containsEntry("outcome", "DENIED").containsEntry("status", 403)
				.containsEntry("actor_role", "finance");
		assertThat(jdbc.sql("SELECT count(*) FROM outcome_demand").query(Integer.class).single()).isZero();
		assertThat(jdbc.sql("SELECT status FROM purchase_order WHERE po_id = 'APR-1-PO01'").query(String.class)
				.single()).isEqualTo("APPROVED");

		when(engine.evaluateOutcomes(any(), any())).thenReturn(json.readTree("{\"forecast\":{}}"));
		mockMvc.perform(TestAuth.as(get("/api/outcomes/evaluation"), "fay", "finance"))
				.andExpect(status().isOk());
		mockMvc.perform(get("/api/outcomes/evaluation")).andExpect(status().isUnauthorized());
	}

	@Test
	void invalidOutcomesAreRejectedWithStableCodes() throws Exception {
		post("/api/outcomes/demand", "pat", "planner",
				"{\"records\":[{\"skuId\":\"SKU-001\",\"regionId\":\"R1\",\"weekStart\":\"2024-12-31\","
						+ "\"quantity\":5}]}")
				.andExpect(status().isBadRequest()).andExpect(jsonPath("$.code").value("INVALID_WEEK"));
		post("/api/outcomes/demand", "pat", "planner",
				"{\"records\":[{\"skuId\":\"SKU-404\",\"regionId\":\"R1\",\"weekStart\":\"2024-12-30\","
						+ "\"quantity\":5}]}")
				.andExpect(status().isNotFound()).andExpect(jsonPath("$.code").value("UNKNOWN_SKU"));
		post("/api/outcomes/demand", "pat", "planner",
				"{\"records\":[{\"skuId\":\"SKU-001\",\"regionId\":\"R1\",\"weekStart\":\"2024-12-30\","
						+ "\"quantity\":-1}]}")
				.andExpect(status().isBadRequest());
		post("/api/outcomes/demand", "pat", "planner",
				"{\"source\":\"GUESSED\",\"records\":[{\"skuId\":\"SKU-001\",\"regionId\":\"R1\","
						+ "\"weekStart\":\"2024-12-30\",\"quantity\":1}]}")
				.andExpect(status().isBadRequest()).andExpect(jsonPath("$.code").value("INVALID_SOURCE"));
		post("/api/outcomes/inventory", "pat", "planner",
				"{\"records\":[{\"skuId\":\"SKU-001\",\"warehouseId\":\"W9\",\"weekStart\":\"2024-12-30\","
						+ "\"onHand\":5}]}")
				.andExpect(status().isNotFound()).andExpect(jsonPath("$.code").value("UNKNOWN_WAREHOUSE"));
		post("/api/outcomes/deliveries", "pat", "planner",
				"{\"poId\":\"PO-404\",\"deliveredOn\":\"2025-01-09\",\"deliveredQuantity\":1}")
				.andExpect(status().isNotFound()).andExpect(jsonPath("$.code").value("UNKNOWN_PURCHASE_ORDER"));
		post("/api/outcomes/deliveries", "pat", "planner",
				"{\"poId\":\"PO-REJ\",\"deliveredOn\":\"2025-01-09\",\"deliveredQuantity\":1}")
				.andExpect(status().isConflict()).andExpect(jsonPath("$.code").value("NOT_DELIVERABLE"));
		post("/api/outcomes/deliveries", "pat", "planner",
				"{\"poId\":\"APR-1-PO01\",\"deliveredOn\":\"2024-12-01\",\"deliveredQuantity\":1}")
				.andExpect(status().isBadRequest()).andExpect(jsonPath("$.code").value("INVALID_DELIVERY_DATE"));
		assertThat(jdbc.sql("SELECT count(*) FROM outcome_demand").query(Integer.class).single()).isZero();
		assertThat(jdbc.sql("SELECT count(*) FROM outcome_delivery").query(Integer.class).single()).isZero();
	}

	@Test
	void theEvaluationSendsSnapshotLatestActualsAndPromisesToTheEngine() throws Exception {
		when(engine.forecastSnapshot(any(), any())).thenReturn(json.readTree("""
				{"modelVersion":"lgbm-test","datasetId":"synthetic-test","asOf":"2024-12-30","intervalLevel":0.8,
				 "points":[{"skuId":"SKU-001","regionId":"R1","weekStart":"2024-12-30","horizon":1,
				            "point":12.0,"lower":4.0,"upper":20.0},
				           {"skuId":"SKU-001","regionId":"R1","weekStart":"2025-01-06","horizon":2,
				            "point":13.0,"lower":5.0,"upper":21.0}]}"""));
		post("/api/outcomes/forecast-snapshots/REC-1", "pat", "planner", "")
				.andExpect(status().isCreated()).andExpect(jsonPath("$.stored").value(2));
		post("/api/outcomes/forecast-snapshots/REC-1", "pat", "planner", "")
				.andExpect(status().isCreated()); // idempotent
		assertThat(jdbc.sql("SELECT count(*) FROM forecast_snapshot").query(Integer.class).single()).isEqualTo(2);

		// a first figure, then a correction: the latest record counts
		post("/api/outcomes/demand", "pat", "planner",
				"{\"records\":[{\"skuId\":\"SKU-001\",\"regionId\":\"R1\",\"weekStart\":\"2024-12-30\","
						+ "\"quantity\":9}]}")
				.andExpect(status().isCreated()).andExpect(jsonPath("$.recorded").value(1));
		post("/api/outcomes/demand", "pat", "planner",
				"{\"records\":[{\"skuId\":\"SKU-001\",\"regionId\":\"R1\",\"weekStart\":\"2024-12-30\","
						+ "\"quantity\":15}]}")
				.andExpect(status().isCreated());
		post("/api/outcomes/inventory", "pat", "planner",
				"{\"records\":[{\"skuId\":\"SKU-001\",\"warehouseId\":\"W1\",\"weekStart\":\"2024-12-30\","
						+ "\"onHand\":0,\"unmetUnits\":3}]}")
				.andExpect(status().isCreated());
		post("/api/outcomes/deliveries", "pat", "planner",
				"{\"poId\":\"APR-1-PO01\",\"deliveredOn\":\"2025-01-08\",\"deliveredQuantity\":100}")
				.andExpect(status().isCreated());

		when(engine.evaluateOutcomes(any(), any())).thenReturn(json.readTree(
				"{\"forecast\":{\"overall\":{\"mae\":3.0},\"awaitingActuals\":1}}"));
		mockMvc.perform(TestAuth.as(get("/api/outcomes/evaluation").param("recommendationId", "REC-1"), "pat",
				"planner"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.recommendationId").value("REC-1"))
				.andExpect(jsonPath("$.forecastModelVersions[0]").value("lgbm-test"))
				.andExpect(jsonPath("$.evaluation.forecast.awaitingActuals").value(1));

		ArgumentCaptor<JsonNode> sent = ArgumentCaptor.forClass(JsonNode.class);
		verify(engine).evaluateOutcomes(any(), sent.capture());
		JsonNode request = sent.getValue();
		assertThat(request.path("forecasts").size()).isEqualTo(2);
		assertThat(request.path("demand").size()).isEqualTo(1);
		assertThat(request.path("demand").get(0).path("quantity").asDouble()).isEqualTo(15.0);
		JsonNode delivery = request.path("deliveries").get(0);
		assertThat(delivery.path("poId").asString()).isEqualTo("APR-1-PO01");
		assertThat(delivery.path("deliveredOn").asString()).isEqualTo("2025-01-08");
		assertThat(delivery.path("expectedDelivery").asString()).isEqualTo("2025-01-06");
		assertThat(delivery.path("promisedReliability").asDouble()).isEqualTo(0.95);
		assertThat(request.path("inventory").get(0).path("unmetUnits").asInt()).isEqualTo(3);
	}

	@Test
	void onlyApprovedRecommendationsGetASnapshotAndUnknownOnesAreNotFound() throws Exception {
		jdbc.sql("UPDATE recommendation SET status = 'REJECTED' WHERE recommendation_id = 'REC-1'").update();
		post("/api/outcomes/forecast-snapshots/REC-1", "pat", "planner", "")
				.andExpect(status().isConflict()).andExpect(jsonPath("$.code").value("NOT_APPROVED"));
		post("/api/outcomes/forecast-snapshots/REC-404", "pat", "planner", "")
				.andExpect(status().isNotFound());
		mockMvc.perform(TestAuth.as(get("/api/outcomes/evaluation").param("recommendationId", "REC-404"), "pat",
				"planner")).andExpect(status().isNotFound());
		verify(engine, never()).forecastSnapshot(any(), any());
	}

}
