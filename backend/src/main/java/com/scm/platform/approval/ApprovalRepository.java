package com.scm.platform.approval;

import java.sql.Array;
import java.sql.SQLException;
import java.time.Instant;
import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;
import tools.jackson.databind.JsonNode;

@Repository
public class ApprovalRepository {

	public record ApprovalRow(String approvalId, String recommendationId, String requestedBy, String requesterRole,
			List<String> requiredRoles, List<String> approvedRoles, List<String> approvers, double orderValue,
			String status, Instant createdAt, Instant updatedAt) {
	}

	public record DecisionRow(String decisionId, String decidedBy, String approverRole, String outcome,
			Instant decidedAt, String rationale) {
	}

	public record LineRow(int lineNo, String supplierId, String skuId, String warehouseId, int quantity,
			double unitPrice, double shippingCost) {
	}

	public record RecommendationRow(String recommendationId, Instant createdAt, String summary, double objectiveValue,
			double expectedServiceLevel, JsonNode assumptions, JsonNode citations, LocalDate horizonStart,
			LocalDate horizonEnd, String status) {
	}

	private static final String APPROVAL_COLUMNS = "approval_id, recommendation_id, requested_by, requester_role,"
			+ " required_roles, approved_roles, approvers, order_value, status, created_at, updated_at";

	private final JdbcClient jdbc;

	private final tools.jackson.databind.json.JsonMapper json;

	public ApprovalRepository(JdbcClient jdbc, tools.jackson.databind.json.JsonMapper json) {
		this.jdbc = jdbc;
		this.json = json;
	}

	public void upsertRecommendation(JsonNode rec) {
		jdbc.sql("""
				INSERT INTO recommendation (recommendation_id, created_at, summary, objective_value,
				    expected_service_level, assumptions, citations, horizon_start, horizon_end, status)
				VALUES (:id, CAST(:createdAt AS timestamptz), :summary, :objective, :service,
				    CAST(:assumptions AS jsonb), CAST(:citations AS jsonb), CAST(:start AS date), CAST(:end AS date),
				    :status)
				ON CONFLICT (recommendation_id) DO UPDATE SET status = EXCLUDED.status""")
				.param("id", rec.path("recommendationId").asString())
				.param("createdAt", rec.path("createdAt").asString())
				.param("summary", rec.path("summary").asString())
				.param("objective", rec.path("objectiveValue").asDouble())
				.param("service", rec.path("expectedServiceLevel").asDouble())
				.param("assumptions", rec.path("assumptions").toString())
				.param("citations", rec.path("citations").toString())
				.param("start", rec.path("horizonStart").asString())
				.param("end", rec.path("horizonEnd").asString())
				.param("status", rec.path("status").asString())
				.update();
		int lineNo = 1;
		for (JsonNode line : rec.path("lines")) {
			jdbc.sql("""
					INSERT INTO recommendation_line (recommendation_id, line_no, supplier_id, sku_id, warehouse_id,
					    quantity, unit_price, shipping_cost)
					VALUES (:id, :no, :supplier, :sku, :warehouse, :qty, :price, :shipping)
					ON CONFLICT DO NOTHING""")
					.param("id", rec.path("recommendationId").asString()).param("no", lineNo++)
					.param("supplier", line.path("supplierId").asString())
					.param("sku", line.path("skuId").asString())
					.param("warehouse", line.path("warehouseId").asString())
					.param("qty", line.path("quantity").asInt())
					.param("price", line.path("unitPrice").asDouble())
					.param("shipping", line.path("shippingCost").asDouble())
					.update();
		}
	}

	public void upsertApproval(JsonNode approval) {
		jdbc.sql("""
				INSERT INTO approval (approval_id, recommendation_id, requested_by, requester_role, required_roles,
				    approved_roles, approvers, order_value, status, created_at, updated_at)
				VALUES (:id, :rec, :by, :role, CAST(:required AS text[]), CAST(:approved AS text[]),
				    CAST(:approvers AS text[]), :value, :status, CAST(:createdAt AS timestamptz), now())
				ON CONFLICT (approval_id) DO UPDATE SET approved_roles = EXCLUDED.approved_roles,
				    approvers = EXCLUDED.approvers, status = EXCLUDED.status, updated_at = now()""")
				.param("id", approval.path("approvalId").asString())
				.param("rec", approval.path("recommendation").path("recommendationId").asString())
				.param("by", approval.path("requestedBy").asString())
				.param("role", approval.path("requesterRole").asString())
				.param("required", pgArray(approval.path("requiredRoles")))
				.param("approved", pgArray(approval.path("approvedRoles")))
				.param("approvers", pgArray(approval.path("approvers")))
				.param("value", approval.path("orderValue").asDouble())
				.param("status", approval.path("status").asString())
				.param("createdAt", approval.path("createdAt").asString())
				.update();
	}

	public void appendDecision(String approvalId, String recommendationId, String decidedBy, String approverRole,
			String outcome, String rationale) {
		int number = jdbc.sql("SELECT count(*) FROM decision WHERE approval_id = :id").param("id", approvalId)
				.query(Integer.class).single() + 1;
		jdbc.sql("""
				INSERT INTO decision (decision_id, recommendation_id, decided_by, outcome, decided_at, rationale,
				    approval_id, approver_role)
				VALUES (:id, :rec, :by, :outcome, now(), :rationale, :approval, :role)""")
				.param("id", "%s-D%03d".formatted(approvalId, number)).param("rec", recommendationId)
				.param("by", decidedBy).param("outcome", outcome).param("rationale", rationale)
				.param("approval", approvalId).param("role", approverRole).update();
	}

	/** One APPROVED purchase order per line of a fully approved recommendation; idempotent. */
	public int createPurchaseOrders(String approvalId, String recommendationId) {
		return jdbc.sql("""
				INSERT INTO purchase_order (po_id, supplier_id, sku_id, warehouse_id, quantity, unit_price, status,
				    created_at, expected_delivery, recommendation_id)
				SELECT :approval || '-PO' || lpad(l.line_no::text, 2, '0'), l.supplier_id, l.sku_id, l.warehouse_id,
				       l.quantity, l.unit_price, 'APPROVED', now(),
				       CURRENT_DATE + COALESCE((SELECT min(o.lead_time_days) FROM supplier_offer o
				            WHERE o.supplier_id = l.supplier_id AND o.sku_id = l.sku_id
				              AND o.valid_from <= r.horizon_start AND o.valid_to >= r.horizon_start), 0),
				       r.recommendation_id
				FROM recommendation_line l JOIN recommendation r USING (recommendation_id)
				WHERE r.recommendation_id = :rec
				ON CONFLICT (po_id) DO NOTHING""")
				.param("approval", approvalId).param("rec", recommendationId).update();
	}

	public List<ApprovalRow> approvals(String status) {
		return jdbc.sql("SELECT " + APPROVAL_COLUMNS + " FROM approval WHERE CAST(:status AS text) IS NULL"
				+ " OR status = :status ORDER BY created_at DESC, approval_id").param("status", status)
				.query((rs, i) -> approvalRow(rs)).list();
	}

	public Optional<ApprovalRow> approval(String approvalId) {
		return jdbc.sql("SELECT " + APPROVAL_COLUMNS + " FROM approval WHERE approval_id = :id")
				.param("id", approvalId).query((rs, i) -> approvalRow(rs)).optional();
	}

	public Optional<ApprovalRow> approvalForRecommendation(String recommendationId) {
		return jdbc.sql("SELECT " + APPROVAL_COLUMNS + " FROM approval WHERE recommendation_id = :id")
				.param("id", recommendationId).query((rs, i) -> approvalRow(rs)).optional();
	}

	public List<DecisionRow> decisions(String approvalId) {
		return jdbc.sql("SELECT decision_id, decided_by, approver_role, outcome, decided_at, rationale FROM decision"
				+ " WHERE approval_id = :id ORDER BY decision_id").param("id", approvalId)
				.query((rs, i) -> new DecisionRow(rs.getString(1), rs.getString(2), rs.getString(3), rs.getString(4),
						rs.getObject(5, OffsetDateTime.class).toInstant(), rs.getString(6)))
				.list();
	}

	public List<RecommendationRow> recommendations(String status) {
		return jdbc.sql(RECOMMENDATION_SELECT + " WHERE CAST(:status AS text) IS NULL OR status = :status"
				+ " ORDER BY created_at DESC, recommendation_id").param("status", status)
				.query((rs, i) -> recommendationRow(rs)).list();
	}

	public Optional<RecommendationRow> recommendation(String id) {
		return jdbc.sql(RECOMMENDATION_SELECT + " WHERE recommendation_id = :id").param("id", id)
				.query((rs, i) -> recommendationRow(rs)).optional();
	}

	public List<LineRow> lines(String recommendationId) {
		return jdbc.sql("SELECT line_no, supplier_id, sku_id, warehouse_id, quantity, unit_price, shipping_cost"
				+ " FROM recommendation_line WHERE recommendation_id = :id ORDER BY line_no")
				.param("id", recommendationId)
				.query((rs, i) -> new LineRow(rs.getInt(1), rs.getString(2), rs.getString(3), rs.getString(4),
						rs.getInt(5), rs.getDouble(6), rs.getDouble(7)))
				.list();
	}

	private static final String RECOMMENDATION_SELECT = "SELECT recommendation_id, created_at, summary,"
			+ " objective_value, expected_service_level, assumptions::text AS assumptions, citations::text AS"
			+ " citations, horizon_start, horizon_end, status FROM recommendation";

	private RecommendationRow recommendationRow(java.sql.ResultSet rs) throws SQLException {
		return new RecommendationRow(rs.getString("recommendation_id"),
				rs.getObject("created_at", OffsetDateTime.class).toInstant(), rs.getString("summary"),
				rs.getDouble("objective_value"), rs.getDouble("expected_service_level"),
				json.readTree(rs.getString("assumptions")), json.readTree(rs.getString("citations")),
				rs.getObject("horizon_start", LocalDate.class), rs.getObject("horizon_end", LocalDate.class),
				rs.getString("status"));
	}

	private static ApprovalRow approvalRow(java.sql.ResultSet rs) throws SQLException {
		return new ApprovalRow(rs.getString("approval_id"), rs.getString("recommendation_id"),
				rs.getString("requested_by"), rs.getString("requester_role"), strings(rs.getArray("required_roles")),
				strings(rs.getArray("approved_roles")), strings(rs.getArray("approvers")),
				rs.getDouble("order_value"), rs.getString("status"),
				rs.getObject("created_at", OffsetDateTime.class).toInstant(),
				rs.getObject("updated_at", OffsetDateTime.class).toInstant());
	}

	private static List<String> strings(Array array) throws SQLException {
		return array == null ? List.of() : List.of((String[]) array.getArray());
	}

	private static String pgArray(JsonNode values) {
		List<String> quoted = new ArrayList<>();
		for (JsonNode value : values) {
			quoted.add("\"" + value.asString().replace("\\", "\\\\").replace("\"", "\\\"") + "\"");
		}
		return "{" + String.join(",", quoted) + "}";
	}

}
