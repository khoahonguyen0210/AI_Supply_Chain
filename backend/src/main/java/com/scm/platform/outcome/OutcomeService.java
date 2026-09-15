package com.scm.platform.outcome;

import com.scm.platform.approval.ApprovalRepository;
import com.scm.platform.approval.ApprovalRepository.LineRow;
import com.scm.platform.approval.ApprovalRepository.RecommendationRow;
import com.scm.platform.error.ApiException;
import com.scm.platform.mlservice.MlEngineClient;
import com.scm.platform.outcome.OutcomeRepository.DeliveryRow;
import com.scm.platform.outcome.OutcomeRepository.DemandRow;
import com.scm.platform.outcome.OutcomeRepository.InventoryRow;
import com.scm.platform.outcome.OutcomeRepository.PurchaseOrderRow;
import com.scm.platform.outcome.OutcomeRepository.SnapshotRow;
import com.scm.platform.security.Actor;
import java.time.DayOfWeek;
import java.time.LocalDate;
import java.time.temporal.ChronoUnit;
import java.util.List;
import java.util.Set;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

/**
 * Outcome capture and evaluation. Java records what happened and gathers it; the engine scores it
 * (docs/feedback-loop.md), so the evaluation rules exist once, in Python.
 */
@Service
public class OutcomeService {

	public static final Set<String> SOURCES = Set.of("RECORDED", "SIMULATED");

	private static final Set<String> DELIVERABLE = Set.of("APPROVED", "PLACED", "DELIVERED");

	private static final int MAX_SNAPSHOT_SKUS = 20;

	private static final int MAX_HORIZON_WEEKS = 8;

	private static final Logger log = LoggerFactory.getLogger(OutcomeService.class);

	public record DemandRecord(String skuId, String regionId, LocalDate weekStart, double quantity) {
	}

	public record InventoryRecord(String skuId, String warehouseId, LocalDate weekStart, int onHand,
			int unmetUnits) {
	}

	private final OutcomeRepository outcomes;

	private final ApprovalRepository approvals;

	private final MlEngineClient engine;

	private final JsonMapper json;

	public OutcomeService(OutcomeRepository outcomes, ApprovalRepository approvals, MlEngineClient engine,
			JsonMapper json) {
		this.outcomes = outcomes;
		this.approvals = approvals;
		this.engine = engine;
		this.json = json;
	}

	@Transactional
	public int recordDemand(Actor actor, String source, List<DemandRecord> records) {
		records.forEach(r -> requireMonday(r.weekStart()));
		requireKnown("sku", "sku_id", records.stream().map(DemandRecord::skuId).toList(), "UNKNOWN_SKU");
		requireKnown("region", "region_id", records.stream().map(DemandRecord::regionId).toList(),
				"UNKNOWN_REGION");
		records.forEach(r -> outcomes.insertDemand(r.skuId(), r.regionId(), r.weekStart(), r.quantity(), source,
				actor.userId()));
		return records.size();
	}

	@Transactional
	public int recordInventory(Actor actor, String source, List<InventoryRecord> records) {
		records.forEach(r -> requireMonday(r.weekStart()));
		requireKnown("sku", "sku_id", records.stream().map(InventoryRecord::skuId).toList(), "UNKNOWN_SKU");
		requireKnown("warehouse", "warehouse_id", records.stream().map(InventoryRecord::warehouseId).toList(),
				"UNKNOWN_WAREHOUSE");
		records.forEach(r -> outcomes.insertInventory(r.skuId(), r.warehouseId(), r.weekStart(), r.onHand(),
				r.unmetUnits(), source, actor.userId()));
		return records.size();
	}

	/** Records a supplier delivery against a purchase order that was approved (or placed). */
	@Transactional
	public PurchaseOrderRow recordDelivery(Actor actor, String poId, LocalDate deliveredOn, int deliveredQuantity,
			String source) {
		PurchaseOrderRow order = outcomes.purchaseOrder(poId)
				.orElseThrow(() -> ApiException.notFound("UNKNOWN_PURCHASE_ORDER", "no purchase order " + poId));
		if (!DELIVERABLE.contains(order.status())) {
			throw ApiException.conflict("NOT_DELIVERABLE",
					"purchase order " + poId + " is " + order.status() + "; only approved orders are delivered");
		}
		if (deliveredOn.isBefore(order.createdOn())) {
			throw ApiException.badRequest("INVALID_DELIVERY_DATE", "delivery is before the order was created");
		}
		outcomes.recordDelivery(poId, deliveredOn, deliveredQuantity, source, actor.userId());
		return outcomes.purchaseOrder(poId).orElseThrow();
	}

	/**
	 * Stores the served model's forecast for an approved recommendation's SKUs over its horizon, so the
	 * forecast the decision relied on can be compared with actual demand later. Idempotent.
	 */
	public int captureForecast(Actor actor, String recommendationId) {
		RecommendationRow recommendation = approvals.recommendation(recommendationId).orElseThrow(
				() -> ApiException.notFound("UNKNOWN_RECOMMENDATION", "no recommendation " + recommendationId));
		if (!"APPROVED".equals(recommendation.status())) {
			throw ApiException.conflict("NOT_APPROVED", "only approved recommendations are tracked");
		}
		List<String> skus = approvals.lines(recommendationId).stream().map(LineRow::skuId).distinct().sorted()
				.limit(MAX_SNAPSHOT_SKUS).toList();
		if (skus.isEmpty()) {
			return 0;
		}
		long days = ChronoUnit.DAYS.between(recommendation.horizonStart(), recommendation.horizonEnd());
		int weeks = (int) Math.max(1, Math.min(MAX_HORIZON_WEEKS, (days + 6) / 7));
		ObjectNode request = json.createObjectNode();
		ArrayNode skuIds = request.putArray("skuIds");
		skus.forEach(skuIds::add);
		request.put("asOf", recommendation.horizonStart().toString());
		request.put("horizonWeeks", weeks);
		JsonNode snapshot = engine.forecastSnapshot(actor, request);
		if (snapshot == null) {
			return 0;
		}
		int stored = 0;
		for (JsonNode point : snapshot.path("points")) {
			outcomes.insertSnapshot(recommendationId, snapshot.path("modelVersion").asString(),
					snapshot.path("datasetId").asString(), recommendation.horizonStart(),
					snapshot.path("intervalLevel").asDouble(), point);
			stored++;
		}
		return stored;
	}

	/** {@link #captureForecast} that never fails the caller: the approval has already been stored. */
	public void captureForecastQuietly(Actor actor, String recommendationId) {
		try {
			captureForecast(actor, recommendationId);
		}
		catch (RuntimeException ex) {
			log.warn("could not record the forecast snapshot for {}; retry with POST"
					+ " /api/outcomes/forecast-snapshots/{}", recommendationId, recommendationId, ex);
		}
	}

	/** Gathers forecasts, recorded outcomes and promises; the engine scores them. */
	public ObjectNode evaluate(Actor actor, String recommendationId) {
		if (recommendationId != null && approvals.recommendation(recommendationId).isEmpty()) {
			throw ApiException.notFound("UNKNOWN_RECOMMENDATION", "no recommendation " + recommendationId);
		}
		List<SnapshotRow> snapshots = outcomes.snapshots(recommendationId);
		List<DemandRow> demand = outcomes.demandForSnapshots(recommendationId);
		List<DeliveryRow> deliveries = outcomes.deliveries(recommendationId);
		List<InventoryRow> inventory = outcomes.inventory(recommendationId);

		ObjectNode request = json.createObjectNode();
		ArrayNode forecasts = request.putArray("forecasts");
		for (SnapshotRow s : snapshots) {
			forecasts.addObject().put("skuId", s.skuId()).put("regionId", s.regionId())
					.put("weekStart", s.weekStart().toString()).put("horizon", s.horizon()).put("point", s.point())
					.put("lower", s.lower()).put("upper", s.upper());
		}
		ArrayNode actuals = request.putArray("demand");
		for (DemandRow d : demand) {
			actuals.addObject().put("skuId", d.skuId()).put("regionId", d.regionId())
					.put("weekStart", d.weekStart().toString()).put("quantity", d.quantity());
		}
		ArrayNode orders = request.putArray("deliveries");
		for (DeliveryRow d : deliveries) {
			ObjectNode row = orders.addObject().put("poId", d.poId()).put("supplierId", d.supplierId())
					.put("orderedQuantity", d.orderedQuantity())
					.put("expectedDelivery", d.expectedDelivery().toString())
					.put("promisedReliability", d.promisedReliability());
			if (d.deliveredOn() != null) {
				row.put("deliveredOn", d.deliveredOn().toString()).put("deliveredQuantity", d.deliveredQuantity());
			}
		}
		ArrayNode stock = request.putArray("inventory");
		for (InventoryRow i : inventory) {
			stock.addObject().put("skuId", i.skuId()).put("warehouseId", i.warehouseId())
					.put("weekStart", i.weekStart().toString()).put("onHand", i.onHand())
					.put("unmetUnits", i.unmetUnits());
		}

		ObjectNode result = json.createObjectNode();
		result.put("recommendationId", recommendationId);
		ArrayNode versions = result.putArray("forecastModelVersions");
		snapshots.stream().map(SnapshotRow::modelVersion).distinct().sorted().forEach(versions::add);
		result.set("evaluation", engine.evaluateOutcomes(actor, request));
		return result;
	}

	private void requireKnown(String table, String column, List<String> ids, String code) {
		List<String> missing = outcomes.missing(table, column, ids);
		if (!missing.isEmpty()) {
			throw ApiException.notFound(code, "unknown " + table + ": " + String.join(", ", missing));
		}
	}

	private static void requireMonday(LocalDate weekStart) {
		if (weekStart.getDayOfWeek() != DayOfWeek.MONDAY) {
			throw ApiException.badRequest("INVALID_WEEK", "weekStart must be a Monday: " + weekStart);
		}
	}

}
