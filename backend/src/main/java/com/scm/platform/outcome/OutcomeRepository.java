package com.scm.platform.outcome;

import java.time.LocalDate;
import java.util.Collection;
import java.util.List;
import java.util.Optional;
import java.util.TreeSet;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;
import tools.jackson.databind.JsonNode;

/**
 * Forecast snapshots and realised outcomes (V7). Every table is append-only; reads take the latest row
 * per key, so a correction is simply a newer record.
 */
@Repository
public class OutcomeRepository {

	public record PurchaseOrderRow(String poId, String supplierId, String skuId, String warehouseId, int quantity,
			String status, LocalDate createdOn, LocalDate expectedDelivery, String recommendationId) {
	}

	public record SnapshotRow(String recommendationId, String modelVersion, String skuId, String regionId,
			LocalDate weekStart, int horizon, double point, double lower, double upper) {
	}

	public record DemandRow(String skuId, String regionId, LocalDate weekStart, double quantity) {
	}

	public record DeliveryRow(String poId, String supplierId, int orderedQuantity, LocalDate expectedDelivery,
			LocalDate deliveredOn, Integer deliveredQuantity, double promisedReliability) {
	}

	public record InventoryRow(String skuId, String warehouseId, LocalDate weekStart, int onHand, int unmetUnits) {
	}

	private final JdbcClient jdbc;

	public OutcomeRepository(JdbcClient jdbc) {
		this.jdbc = jdbc;
	}

	/** The ids among {@code ids} that are not in {@code table.column} (a fixed, trusted identifier pair). */
	public List<String> missing(String table, String column, Collection<String> ids) {
		if (ids.isEmpty()) {
			return List.of();
		}
		List<String> known = jdbc.sql("SELECT " + column + " FROM " + table + " WHERE " + column + " IN (:ids)")
				.param("ids", new TreeSet<>(ids)).query(String.class).list();
		return new TreeSet<>(ids).stream().filter(id -> !known.contains(id)).toList();
	}

	public void insertSnapshot(String recommendationId, String modelVersion, String datasetId, LocalDate asOf,
			double intervalLevel, JsonNode point) {
		jdbc.sql("""
				INSERT INTO forecast_snapshot (recommendation_id, model_version, dataset_id, sku_id, region_id, as_of,
				    week_start, horizon, point, lower_bound, upper_bound, interval_level)
				VALUES (:rec, :model, :dataset, :sku, :region, :asOf, CAST(:week AS date), :horizon, :point, :lower,
				    :upper, :level)
				ON CONFLICT (recommendation_id, sku_id, region_id, week_start) DO NOTHING""")
				.param("rec", recommendationId).param("model", modelVersion).param("dataset", datasetId)
				.param("sku", point.path("skuId").asString()).param("region", point.path("regionId").asString())
				.param("asOf", asOf).param("week", point.path("weekStart").asString())
				.param("horizon", point.path("horizon").asInt()).param("point", point.path("point").asDouble())
				.param("lower", point.path("lower").asDouble()).param("upper", point.path("upper").asDouble())
				.param("level", intervalLevel).update();
	}

	public void insertDemand(String skuId, String regionId, LocalDate weekStart, double quantity, String source,
			String recordedBy) {
		jdbc.sql("""
				INSERT INTO outcome_demand (sku_id, region_id, week_start, quantity, source, recorded_by)
				VALUES (:sku, :region, :week, :qty, :source, :by)""").param("sku", skuId).param("region", regionId)
				.param("week", weekStart).param("qty", quantity).param("source", source).param("by", recordedBy)
				.update();
	}

	public void insertInventory(String skuId, String warehouseId, LocalDate weekStart, int onHand, int unmetUnits,
			String source, String recordedBy) {
		jdbc.sql("""
				INSERT INTO outcome_inventory (sku_id, warehouse_id, week_start, on_hand, unmet_units, source,
				    recorded_by)
				VALUES (:sku, :warehouse, :week, :onHand, :unmet, :source, :by)""").param("sku", skuId)
				.param("warehouse", warehouseId).param("week", weekStart).param("onHand", onHand)
				.param("unmet", unmetUnits).param("source", source).param("by", recordedBy).update();
	}

	/** Appends the delivery record and moves the purchase order to DELIVERED with the latest figures. */
	public void recordDelivery(String poId, LocalDate deliveredOn, int deliveredQuantity, String source,
			String recordedBy) {
		jdbc.sql("""
				INSERT INTO outcome_delivery (po_id, delivered_on, delivered_quantity, source, recorded_by)
				VALUES (:po, :on, :qty, :source, :by)""").param("po", poId).param("on", deliveredOn)
				.param("qty", deliveredQuantity).param("source", source).param("by", recordedBy).update();
		jdbc.sql("""
				UPDATE purchase_order SET status = 'DELIVERED', delivered_at = :on, delivered_quantity = :qty
				WHERE po_id = :po""").param("po", poId).param("on", deliveredOn).param("qty", deliveredQuantity)
				.update();
	}

	public Optional<PurchaseOrderRow> purchaseOrder(String poId) {
		return jdbc.sql("""
				SELECT po_id, supplier_id, sku_id, warehouse_id, quantity, status, created_at::date, expected_delivery,
				       recommendation_id
				FROM purchase_order WHERE po_id = :po""").param("po", poId)
				.query((rs, i) -> new PurchaseOrderRow(rs.getString(1), rs.getString(2), rs.getString(3),
						rs.getString(4), rs.getInt(5), rs.getString(6), rs.getObject(7, LocalDate.class),
						rs.getObject(8, LocalDate.class), rs.getString(9)))
				.optional();
	}

	/** Forecast points, for one recommendation or (null) for every approved recommendation. */
	public List<SnapshotRow> snapshots(String recommendationId) {
		return jdbc.sql("""
				SELECT recommendation_id, model_version, sku_id, region_id, week_start, horizon, point, lower_bound,
				       upper_bound
				FROM forecast_snapshot
				WHERE CAST(:rec AS text) IS NULL OR recommendation_id = :rec
				ORDER BY recommendation_id, sku_id, region_id, week_start""").param("rec", recommendationId)
				.query((rs, i) -> new SnapshotRow(rs.getString(1), rs.getString(2), rs.getString(3),
						rs.getString(4), rs.getObject(5, LocalDate.class), rs.getInt(6), rs.getDouble(7),
						rs.getDouble(8), rs.getDouble(9)))
				.list();
	}

	/** Latest recorded demand for the weeks a forecast snapshot covers. */
	public List<DemandRow> demandForSnapshots(String recommendationId) {
		return jdbc.sql("""
				SELECT DISTINCT ON (d.sku_id, d.region_id, d.week_start) d.sku_id, d.region_id, d.week_start,
				       d.quantity
				FROM outcome_demand d
				WHERE EXISTS (SELECT 1 FROM forecast_snapshot f
				              WHERE f.sku_id = d.sku_id AND f.region_id = d.region_id AND f.week_start = d.week_start
				                AND (CAST(:rec AS text) IS NULL OR f.recommendation_id = :rec))
				ORDER BY d.sku_id, d.region_id, d.week_start, d.outcome_id DESC""").param("rec", recommendationId)
				.query((rs, i) -> new DemandRow(rs.getString(1), rs.getString(2), rs.getObject(3, LocalDate.class),
						rs.getDouble(4)))
				.list();
	}

	/** Purchase orders created from approved recommendations, with their latest recorded delivery. */
	public List<DeliveryRow> deliveries(String recommendationId) {
		return jdbc.sql("""
				SELECT p.po_id, p.supplier_id, p.quantity, p.expected_delivery, d.delivered_on, d.delivered_quantity,
				       s.reliability
				FROM purchase_order p
				JOIN supplier s USING (supplier_id)
				LEFT JOIN LATERAL (SELECT delivered_on, delivered_quantity FROM outcome_delivery o
				                   WHERE o.po_id = p.po_id ORDER BY outcome_id DESC LIMIT 1) d ON true
				WHERE p.recommendation_id IS NOT NULL
				  AND (CAST(:rec AS text) IS NULL OR p.recommendation_id = :rec)
				ORDER BY p.po_id""").param("rec", recommendationId)
				.query((rs, i) -> new DeliveryRow(rs.getString(1), rs.getString(2), rs.getInt(3),
						rs.getObject(4, LocalDate.class), rs.getObject(5, LocalDate.class),
						(Integer) rs.getObject(6), rs.getDouble(7)))
				.list();
	}

	/**
	 * Latest recorded stock per (SKU, warehouse, week): for one recommendation, the cells it ordered for from
	 * its horizon start; otherwise every record.
	 */
	public List<InventoryRow> inventory(String recommendationId) {
		return jdbc.sql("""
				SELECT DISTINCT ON (i.sku_id, i.warehouse_id, i.week_start) i.sku_id, i.warehouse_id, i.week_start,
				       i.on_hand, i.unmet_units
				FROM outcome_inventory i
				WHERE CAST(:rec AS text) IS NULL OR EXISTS (
				    SELECT 1 FROM recommendation_line l JOIN recommendation r USING (recommendation_id)
				    WHERE l.recommendation_id = :rec AND l.sku_id = i.sku_id AND l.warehouse_id = i.warehouse_id
				      AND i.week_start >= r.horizon_start)
				ORDER BY i.sku_id, i.warehouse_id, i.week_start, i.outcome_id DESC""").param("rec", recommendationId)
				.query((rs, i) -> new InventoryRow(rs.getString(1), rs.getString(2), rs.getObject(3, LocalDate.class),
						rs.getInt(4), rs.getInt(5)))
				.list();
	}

}
