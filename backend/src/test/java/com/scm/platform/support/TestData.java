package com.scm.platform.support;

import org.springframework.jdbc.core.simple.JdbcClient;

public final class TestData {

	private TestData() {
	}

	public static void reset(JdbcClient jdbc) {
		jdbc.sql("""
				TRUNCATE region, sku, supplier, warehouse, scenario, recommendation, knowledge_document, job,
				    agent_conversation, approval, demand_observation, inventory_position, purchase_order CASCADE""")
				.update();
	}

	public static void seedMasterData(JdbcClient jdbc) {
		reset(jdbc);
		jdbc.sql("INSERT INTO region VALUES ('R1', 'North'), ('R2', 'South')").update();
		jdbc.sql("INSERT INTO warehouse VALUES ('W1', 'Hub', 'R1', 1000, 0.5)").update();
		jdbc.sql("INSERT INTO sku VALUES ('SKU-001', 'Widget', 'home', 20.0, 0.1, '{ISO9001}'),"
				+ " ('SKU-002', 'Gadget', 'home', 35.0, 0.2, '{}')").update();
		jdbc.sql("INSERT INTO supplier VALUES ('SUP-1', 'Acme', 'R1', 0.95, 0.9, '{ISO9001}'),"
				+ " ('SUP-2', 'Budget Co', 'R2', 0.70, 0.8, '{}')").update();
		jdbc.sql("INSERT INTO supplier_contract VALUES ('C-1', 'SUP-1', 'ACTIVE', '2024-01-01', '2025-12-31', 30, 50000)")
				.update();
		jdbc.sql("INSERT INTO supplier_offer VALUES ('O-1', 'SUP-1', 'SKU-001', 12.5, 10, 500, 7,"
				+ " '2024-01-01', '2025-12-31')").update();
		jdbc.sql("INSERT INTO supplier_offer_shipping VALUES ('O-1', 'W1', 0.4)").update();
		jdbc.sql("INSERT INTO inventory_position VALUES ('SKU-001', 'W1', '2024-12-23T00:00:00Z', 50, 0, 10),"
				+ " ('SKU-001', 'W1', '2024-12-30T00:00:00Z', 80, 20, 10)").update();
		for (int week = 0; week < 5; week++) {
			jdbc.sql("INSERT INTO demand_observation VALUES ('synthetic', 'SKU-001', 'R1', CAST(:d AS date), :q, now()),"
					+ " ('synthetic', 'SKU-001', 'R2', CAST(:d AS date), :q2, now())")
					.param("d", java.time.LocalDate.of(2024, 12, 2).plusWeeks(week).toString())
					.param("q", 10 + week).param("q2", 20 + week).update();
		}
	}

	public static void seedDocuments(JdbcClient jdbc) {
		jdbc.sql("""
				INSERT INTO knowledge_document (document_id, version, doc_type, title, effective_date, expiry_date,
				    supplier_id, allowed_roles, content, content_sha256) VALUES
				('POL-1', 'v1', 'POLICY', 'Approvals', '2024-01-01', '2024-06-30', NULL, '{planner,admin}', 'old text',
				    repeat('a', 64)),
				('POL-1', 'v2', 'POLICY', 'Approvals', '2024-07-01', NULL, NULL, '{planner,admin}', 'new text',
				    repeat('b', 64)),
				('CON-1', 'v1', 'CONTRACT', 'Acme contract', '2024-01-01', NULL, 'SUP-1', '{finance,admin}',
				    'finance only text', repeat('c', 64))""").update();
	}

}
