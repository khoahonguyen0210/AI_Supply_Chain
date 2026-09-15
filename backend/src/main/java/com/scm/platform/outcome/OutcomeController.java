package com.scm.platform.outcome;

import com.scm.platform.error.ApiException;
import com.scm.platform.outcome.OutcomeRepository.PurchaseOrderRow;
import com.scm.platform.outcome.OutcomeService.DemandRecord;
import com.scm.platform.outcome.OutcomeService.InventoryRecord;
import com.scm.platform.security.Actor;
import com.scm.platform.security.Roles;
import jakarta.validation.Valid;
import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.PositiveOrZero;
import jakarta.validation.constraints.Size;
import java.time.LocalDate;
import java.util.List;
import java.util.Map;
import org.springframework.http.HttpStatus;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.ResponseStatus;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.node.ObjectNode;

/**
 * Outcome capture (what actually happened after a decision) and its evaluation. Recording needs a planning
 * role; every write is audited by the audit filter. Records are append-only: a correction is a new record.
 */
@RestController
@RequestMapping("/api/outcomes")
public class OutcomeController {

	private static final int MAX_RECORDS = 5000;

	private final OutcomeService outcomes;

	public OutcomeController(OutcomeService outcomes) {
		this.outcomes = outcomes;
	}

	public record DemandEntry(@NotBlank String skuId, @NotBlank String regionId, @NotNull LocalDate weekStart,
			@NotNull @PositiveOrZero Double quantity) {
	}

	public record DemandRequest(String source, @NotEmpty @Size(max = MAX_RECORDS) List<@Valid DemandEntry> records) {
	}

	public record InventoryEntry(@NotBlank String skuId, @NotBlank String warehouseId, @NotNull LocalDate weekStart,
			@NotNull @PositiveOrZero Integer onHand, @PositiveOrZero Integer unmetUnits) {
	}

	public record InventoryRequest(String source,
			@NotEmpty @Size(max = MAX_RECORDS) List<@Valid InventoryEntry> records) {
	}

	public record DeliveryRequest(@NotBlank String poId, @NotNull LocalDate deliveredOn,
			@NotNull @Min(0) @Max(100_000_000) Integer deliveredQuantity, String source) {
	}

	@PostMapping("/demand")
	@ResponseStatus(HttpStatus.CREATED)
	public Map<String, Integer> recordDemand(Actor actor, @Valid @RequestBody DemandRequest request) {
		Roles.require(actor, Roles.PLANNING);
		List<DemandRecord> records = request.records().stream()
				.map(e -> new DemandRecord(e.skuId(), e.regionId(), e.weekStart(), e.quantity())).toList();
		return Map.of("recorded", outcomes.recordDemand(actor, source(request.source()), records));
	}

	@PostMapping("/inventory")
	@ResponseStatus(HttpStatus.CREATED)
	public Map<String, Integer> recordInventory(Actor actor, @Valid @RequestBody InventoryRequest request) {
		Roles.require(actor, Roles.PLANNING);
		List<InventoryRecord> records = request.records().stream()
				.map(e -> new InventoryRecord(e.skuId(), e.warehouseId(), e.weekStart(), e.onHand(),
						e.unmetUnits() == null ? 0 : e.unmetUnits()))
				.toList();
		return Map.of("recorded", outcomes.recordInventory(actor, source(request.source()), records));
	}

	@PostMapping("/deliveries")
	@ResponseStatus(HttpStatus.CREATED)
	public PurchaseOrderRow recordDelivery(Actor actor, @Valid @RequestBody DeliveryRequest request) {
		Roles.require(actor, Roles.PLANNING);
		return outcomes.recordDelivery(actor, request.poId(), request.deliveredOn(), request.deliveredQuantity(),
				source(request.source()));
	}

	/** Records (again) the forecast an approved recommendation relied on; normally done on approval. */
	@PostMapping("/forecast-snapshots/{recommendationId}")
	@ResponseStatus(HttpStatus.CREATED)
	public Map<String, Integer> captureForecast(Actor actor, @PathVariable String recommendationId) {
		Roles.require(actor, Roles.PLANNING);
		return Map.of("stored", outcomes.captureForecast(actor, recommendationId));
	}

	/** Forecast versus actual demand, promised versus actual delivery, and stock outcomes. */
	@GetMapping("/evaluation")
	public ObjectNode evaluation(Actor actor, @RequestParam(required = false) String recommendationId) {
		return outcomes.evaluate(actor, recommendationId);
	}

	private static String source(String source) {
		String value = source == null ? "RECORDED" : source;
		if (!OutcomeService.SOURCES.contains(value)) {
			throw ApiException.badRequest("INVALID_SOURCE", "source must be one of " + OutcomeService.SOURCES);
		}
		return value;
	}

}
