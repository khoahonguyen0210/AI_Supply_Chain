package com.scm.platform.catalog;

import java.time.LocalDate;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

/** Read access to master data, demand history and inventory. Planning computations are not done here. */
@Repository
public class CatalogRepository {

	public record Sku(String skuId, String name, String category, double unitPrice, double unitVolume,
			List<String> requiredCertifications) {
	}

	public record Supplier(String supplierId, String name, String regionId, double reliability, double qualityScore,
			List<String> certifications) {
	}

	public record Contract(String contractId, String status, LocalDate effectiveFrom, LocalDate effectiveTo,
			int paymentTermsDays, Double maxOrderValue) {
	}

	public record Offer(String offerId, String skuId, double unitPrice, int moq, int capacityPerWeek,
			int leadTimeDays, LocalDate validFrom, LocalDate validTo) {
	}

	public record DemandPoint(String skuId, String regionId, LocalDate periodStart, double quantity) {
	}

	public record InventoryRow(String skuId, String warehouseId, OffsetDateTime asOf, int onHand, int incoming,
			int safetyStock) {
	}

	private final JdbcClient jdbc;

	public CatalogRepository(JdbcClient jdbc) {
		this.jdbc = jdbc;
	}

	public List<Sku> skus() {
		return jdbc.sql("SELECT sku_id, name, category, unit_price, unit_volume, required_certifications"
				+ " FROM sku ORDER BY sku_id").query((rs, i) -> new Sku(rs.getString(1), rs.getString(2),
						rs.getString(3), rs.getDouble(4), rs.getDouble(5), array(rs.getArray(6)))).list();
	}

	public List<Supplier> suppliers(String regionId, String certification, Double minReliability) {
		return jdbc.sql("""
				SELECT supplier_id, name, region_id, reliability, quality_score, certifications FROM supplier
				WHERE (CAST(:region AS text) IS NULL OR region_id = :region)
				  AND (CAST(:cert AS text) IS NULL OR :cert = ANY (certifications))
				  AND (CAST(:minRel AS numeric) IS NULL OR reliability >= :minRel)
				ORDER BY supplier_id""")
				.param("region", regionId).param("cert", certification).param("minRel", minReliability)
				.query((rs, i) -> new Supplier(rs.getString(1), rs.getString(2), rs.getString(3), rs.getDouble(4),
						rs.getDouble(5), array(rs.getArray(6))))
				.list();
	}

	public Optional<Supplier> supplier(String supplierId) {
		return jdbc.sql("SELECT supplier_id, name, region_id, reliability, quality_score, certifications"
				+ " FROM supplier WHERE supplier_id = :id").param("id", supplierId)
				.query((rs, i) -> new Supplier(rs.getString(1), rs.getString(2), rs.getString(3), rs.getDouble(4),
						rs.getDouble(5), array(rs.getArray(6))))
				.optional();
	}

	public List<Contract> contracts(String supplierId) {
		return jdbc.sql("SELECT contract_id, status, effective_from, effective_to, payment_terms_days,"
				+ " max_order_value FROM supplier_contract WHERE supplier_id = :id ORDER BY effective_from DESC")
				.param("id", supplierId)
				.query((rs, i) -> new Contract(rs.getString(1), rs.getString(2),
						rs.getObject(3, LocalDate.class), rs.getObject(4, LocalDate.class), rs.getInt(5),
						rs.getObject(6) == null ? null : rs.getDouble(6)))
				.list();
	}

	public List<Offer> offers(String supplierId) {
		return jdbc.sql("SELECT offer_id, sku_id, unit_price, moq, capacity_per_week, lead_time_days, valid_from,"
				+ " valid_to FROM supplier_offer WHERE supplier_id = :id ORDER BY sku_id, valid_from")
				.param("id", supplierId)
				.query((rs, i) -> new Offer(rs.getString(1), rs.getString(2), rs.getDouble(3), rs.getInt(4),
						rs.getInt(5), rs.getInt(6), rs.getObject(7, LocalDate.class),
						rs.getObject(8, LocalDate.class)))
				.list();
	}

	/** Weekly demand, oldest first; {@code limitWeeks} keeps only the most recent weeks of each series. */
	public List<DemandPoint> demand(String source, String skuId, String regionId, int limitWeeks) {
		return jdbc.sql("""
				SELECT sku_id, region_id, period_start, quantity FROM (
				    SELECT sku_id, region_id, period_start, quantity,
				           row_number() OVER (PARTITION BY sku_id, region_id ORDER BY period_start DESC) AS recency
				    FROM demand_observation
				    WHERE source = :source AND sku_id = :sku AND (CAST(:region AS text) IS NULL OR region_id = :region)
				) recent WHERE recency <= :limit ORDER BY region_id, period_start""")
				.param("source", source).param("sku", skuId).param("region", regionId).param("limit", limitWeeks)
				.query((rs, i) -> new DemandPoint(rs.getString(1), rs.getString(2), rs.getObject(3, LocalDate.class),
						rs.getDouble(4)))
				.list();
	}

	/** The latest position of each warehouse for the SKU. */
	public List<InventoryRow> inventory(String skuId) {
		return jdbc.sql("""
				SELECT DISTINCT ON (warehouse_id) sku_id, warehouse_id, as_of, on_hand, incoming, safety_stock
				FROM inventory_position WHERE sku_id = :sku ORDER BY warehouse_id, as_of DESC""")
				.param("sku", skuId)
				.query((rs, i) -> new InventoryRow(rs.getString(1), rs.getString(2),
						rs.getObject(3, OffsetDateTime.class), rs.getInt(4), rs.getInt(5), rs.getInt(6)))
				.list();
	}

	public boolean skuExists(String skuId) {
		return jdbc.sql("SELECT count(*) FROM sku WHERE sku_id = :id").param("id", skuId).query(Integer.class)
				.single() > 0;
	}

	private static List<String> array(java.sql.Array value) throws java.sql.SQLException {
		return value == null ? List.of() : List.of((String[]) value.getArray());
	}

}
