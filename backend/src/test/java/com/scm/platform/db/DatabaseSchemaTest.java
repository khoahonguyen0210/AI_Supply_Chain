package com.scm.platform.db;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;

import com.scm.platform.support.PostgresContainerConfig;
import java.util.List;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.dao.DataAccessException;
import org.springframework.jdbc.core.simple.JdbcClient;

@SpringBootTest
@Import(PostgresContainerConfig.class)
class DatabaseSchemaTest {

	private static final List<String> EXPECTED_TABLES = List.of(
			"region", "sku", "supplier", "warehouse", "fulfillment_lane", "supplier_contract",
			"supplier_offer", "supplier_offer_shipping", "sales_order", "demand_observation",
			"inventory_position", "scenario", "recommendation", "recommendation_line",
			"purchase_order", "decision", "knowledge_document", "knowledge_chunk");

	private static final List<String> EXPECTED_INDEXES = List.of(
			"supplier_offer_sku_validity", "sales_order_series", "demand_observation_period",
			"inventory_position_warehouse", "purchase_order_sku_created", "purchase_order_status",
			"recommendation_status_created", "decision_recommendation",
			"knowledge_chunk_embedding_hnsw", "knowledge_chunk_tsv_gin", "knowledge_document_validity");

	@Autowired
	private JdbcClient jdbc;

	@BeforeEach
	void resetData() {
		jdbc.sql("TRUNCATE region, sku, supplier, warehouse, scenario, recommendation, knowledge_document CASCADE")
				.update();
		jdbc.sql("INSERT INTO region VALUES ('R1', 'North')").update();
		jdbc.sql("INSERT INTO supplier VALUES ('SUP-1', 'Acme', 'R1', 0.9, 0.9, '{ISO9001}')").update();
	}

	@Test
	void everyMigrationAppliedSuccessfully() {
		List<String> versions = jdbc
				.sql("SELECT version FROM flyway_schema_history WHERE success ORDER BY installed_rank")
				.query(String.class).list();
		assertThat(versions).containsExactly("1", "2");
	}

	@Test
	void allCoreAndKnowledgeTablesExist() {
		List<String> tables = jdbc.sql(
				"SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'")
				.query(String.class).list();
		assertThat(tables).containsAll(EXPECTED_TABLES);
	}

	@Test
	void indexesExistForMainQueryPaths() {
		List<String> indexes = jdbc.sql("SELECT indexname FROM pg_indexes WHERE schemaname = 'public'")
				.query(String.class).list();
		assertThat(indexes).containsAll(EXPECTED_INDEXES);
	}

	@Test
	void pgvectorExtensionIsInstalled() {
		Integer count = jdbc.sql("SELECT count(*) FROM pg_extension WHERE extname = 'vector'")
				.query(Integer.class).single();
		assertThat(count).isEqualTo(1);
	}

	@Test
	void constraintsRejectInvalidRows() {
		assertThatThrownBy(() -> jdbc.sql("INSERT INTO supplier VALUES ('S2', 'Bad', 'R1', 1.5, 0.5, '{}')").update())
				.isInstanceOf(DataAccessException.class);
		assertThatThrownBy(() -> jdbc.sql("INSERT INTO supplier VALUES ('S3', 'Orphan', 'NOPE', 0.5, 0.5, '{}')").update())
				.isInstanceOf(DataAccessException.class);
		assertThatThrownBy(() -> jdbc.sql(
				"INSERT INTO supplier_contract VALUES ('C1', 'SUP-1', 'ACTIVE', '2025-02-01', '2025-01-01', 30, NULL)")
				.update()).isInstanceOf(DataAccessException.class);
	}

	@Test
	void offerRoundTripWithShipping() {
		jdbc.sql("INSERT INTO sku VALUES ('SKU-1', 'Widget', 'hardware', 10, 0.5, '{}')").update();
		jdbc.sql("INSERT INTO warehouse VALUES ('WH-1', 'Hub', 'R1', 1000, 0.05)").update();
		jdbc.sql("INSERT INTO supplier_offer VALUES ('O1', 'SUP-1', 'SKU-1', 5.5, 50, 500, 14, '2025-01-01', '2025-12-31')")
				.update();
		jdbc.sql("INSERT INTO supplier_offer_shipping VALUES ('O1', 'WH-1', 0.4)").update();

		Double shipping = jdbc.sql("""
				SELECT s.cost_per_unit::float8 FROM supplier_offer o
				JOIN supplier_offer_shipping s USING (offer_id)
				WHERE o.sku_id = 'SKU-1' AND DATE '2025-06-01' BETWEEN o.valid_from AND o.valid_to
				""").query(Double.class).single();
		assertThat(shipping).isEqualTo(0.4);
	}

	@Test
	void decisionsAreAppendOnly() {
		jdbc.sql("INSERT INTO recommendation (recommendation_id, created_at, summary, objective_value, "
				+ "expected_service_level, horizon_start, horizon_end) "
				+ "VALUES ('REC-1', now(), 'Buy', 100, 0.95, '2025-01-01', '2025-02-01')").update();
		jdbc.sql("INSERT INTO decision VALUES ('DEC-1', 'REC-1', 'planner', 'APPROVED', now(), NULL)").update();

		assertThatThrownBy(() -> jdbc.sql("UPDATE decision SET outcome = 'REJECTED'").update())
				.hasMessageContaining("append-only");
		assertThatThrownBy(() -> jdbc.sql("DELETE FROM decision").update())
				.hasMessageContaining("append-only");
	}

}
