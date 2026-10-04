package com.scm.platform.catalog;

import com.scm.platform.catalog.CatalogRepository.Contract;
import com.scm.platform.catalog.CatalogRepository.DemandPoint;
import com.scm.platform.catalog.CatalogRepository.InventoryRow;
import com.scm.platform.catalog.CatalogRepository.Offer;
import com.scm.platform.catalog.CatalogRepository.Region;
import com.scm.platform.catalog.CatalogRepository.Sku;
import com.scm.platform.catalog.CatalogRepository.Supplier;
import com.scm.platform.error.ApiException;
import com.scm.platform.mlservice.MlEngineClient;
import com.scm.platform.security.Actor;
import com.scm.platform.security.Roles;
import java.util.List;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.JsonNode;

@RestController
@RequestMapping("/api")
public class CatalogController {

	private static final String DEMAND_SOURCE = "synthetic";

	private static final int MAX_DEMAND_WEEKS = 520;

	private final CatalogRepository catalog;

	private final MlEngineClient engine;

	public CatalogController(CatalogRepository catalog, MlEngineClient engine) {
		this.catalog = catalog;
		this.engine = engine;
	}

	public record SupplierDetail(Supplier supplier, List<Contract> contracts, List<Offer> offers) {
	}

	@GetMapping("/regions")
	public List<Region> regions(Actor actor) {
		return catalog.regions();
	}

	@GetMapping("/skus")
	public List<Sku> skus(Actor actor) {
		return catalog.skus();
	}

	@GetMapping("/demand")
	public List<DemandPoint> demand(Actor actor, @RequestParam String skuId,
			@RequestParam(required = false) String regionId, @RequestParam(defaultValue = "52") int weeks) {
		requireSku(skuId);
		return catalog.demand(DEMAND_SOURCE, skuId, regionId, Math.max(1, Math.min(weeks, MAX_DEMAND_WEEKS)));
	}

	@GetMapping("/inventory")
	public List<InventoryRow> inventory(Actor actor, @RequestParam String skuId) {
		requireSku(skuId);
		return catalog.inventory(skuId);
	}

	@GetMapping("/suppliers")
	public List<Supplier> suppliers(Actor actor, @RequestParam(required = false) String regionId,
			@RequestParam(required = false) String certification,
			@RequestParam(required = false) Double minReliability) {
		return catalog.suppliers(regionId, certification, minReliability);
	}

	@GetMapping("/suppliers/{supplierId}")
	public SupplierDetail supplier(Actor actor, @PathVariable String supplierId) {
		Supplier supplier = catalog.supplier(supplierId)
				.orElseThrow(() -> ApiException.notFound("UNKNOWN_SUPPLIER", "no supplier " + supplierId));
		return new SupplierDetail(supplier, catalog.contracts(supplierId), catalog.offers(supplierId));
	}

	@GetMapping("/suppliers/{supplierId}/performance")
	public JsonNode performance(Actor actor, @PathVariable String supplierId) {
		return engine.supplierPerformance(actor, supplierId);
	}

	@PostMapping("/suppliers/search")
	public JsonNode search(Actor actor, @RequestBody JsonNode request) {
		Roles.require(actor, Roles.PLANNING);
		return engine.searchSuppliers(actor, request);
	}

	private void requireSku(String skuId) {
		if (!catalog.skuExists(skuId)) {
			throw ApiException.notFound("UNKNOWN_SKU", "no SKU " + skuId);
		}
	}

}
