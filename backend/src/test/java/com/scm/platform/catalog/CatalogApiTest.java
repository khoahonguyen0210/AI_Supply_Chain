package com.scm.platform.catalog;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.ArgumentMatchers.eq;
import static org.mockito.Mockito.never;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.scm.platform.mlservice.MlEngineClient;
import com.scm.platform.mlservice.MlServiceException;
import com.scm.platform.security.Actor;
import com.scm.platform.support.PostgresContainerConfig;
import com.scm.platform.support.TestAuth;
import com.scm.platform.support.TestData;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import tools.jackson.databind.json.JsonMapper;

@SpringBootTest
@AutoConfigureMockMvc
@Import(PostgresContainerConfig.class)
class CatalogApiTest {

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

	private static MockHttpServletRequestBuilder as(MockHttpServletRequestBuilder request, String role) {
		return TestAuth.as(request, "pat", role);
	}

	@Test
	void listsSkus() throws Exception {
		mockMvc.perform(as(get("/api/skus"), "planner"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.length()").value(2))
				.andExpect(jsonPath("$[0].skuId").value("SKU-001"))
				.andExpect(jsonPath("$[0].requiredCertifications[0]").value("ISO9001"))
				.andExpect(jsonPath("$[1].requiredCertifications.length()").value(0));
	}

	@Test
	void demandIsWeeklyOldestFirstAndLimitedToRecentWeeks() throws Exception {
		mockMvc.perform(as(get("/api/demand").param("skuId", "SKU-001").param("regionId", "R1").param("weeks", "3"),
						"planner"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.length()").value(3))
				.andExpect(jsonPath("$[0].periodStart").value("2024-12-16"))
				.andExpect(jsonPath("$[2].periodStart").value("2024-12-30"))
				.andExpect(jsonPath("$[2].quantity").value(14.0));
		mockMvc.perform(as(get("/api/demand").param("skuId", "SKU-001"), "planner"))
				.andExpect(jsonPath("$.length()").value(10));
		mockMvc.perform(as(get("/api/demand").param("skuId", "NOPE"), "planner"))
				.andExpect(status().isNotFound()).andExpect(jsonPath("$.code").value("UNKNOWN_SKU"));
	}

	@Test
	void inventoryShowsTheLatestPositionPerWarehouse() throws Exception {
		mockMvc.perform(as(get("/api/inventory").param("skuId", "SKU-001"), "planner"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.length()").value(1))
				.andExpect(jsonPath("$[0].onHand").value(80))
				.andExpect(jsonPath("$[0].incoming").value(20));
	}

	@Test
	void suppliersCanBeFiltered() throws Exception {
		mockMvc.perform(as(get("/api/suppliers"), "planner")).andExpect(jsonPath("$.length()").value(2));
		mockMvc.perform(as(get("/api/suppliers").param("certification", "ISO9001"), "planner"))
				.andExpect(jsonPath("$.length()").value(1)).andExpect(jsonPath("$[0].supplierId").value("SUP-1"));
		mockMvc.perform(as(get("/api/suppliers").param("regionId", "R2").param("minReliability", "0.6"), "planner"))
				.andExpect(jsonPath("$.length()").value(1)).andExpect(jsonPath("$[0].supplierId").value("SUP-2"));
		mockMvc.perform(as(get("/api/suppliers").param("minReliability", "0.99"), "planner"))
				.andExpect(jsonPath("$.length()").value(0));
	}

	@Test
	void supplierDetailIncludesContractsAndOffers() throws Exception {
		mockMvc.perform(as(get("/api/suppliers/SUP-1"), "planner"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.supplier.name").value("Acme"))
				.andExpect(jsonPath("$.contracts[0].status").value("ACTIVE"))
				.andExpect(jsonPath("$.contracts[0].maxOrderValue").value(50000.0))
				.andExpect(jsonPath("$.offers[0].moq").value(10));
		mockMvc.perform(as(get("/api/suppliers/NOPE"), "planner"))
				.andExpect(status().isNotFound()).andExpect(jsonPath("$.code").value("UNKNOWN_SUPPLIER"));
	}

	@Test
	void rankingAndPerformanceAreRelayedToTheEngineAsTheCaller() throws Exception {
		when(engine.searchSuppliers(any(), any())).thenReturn(json.readTree("{\"ranked\":[{\"rank\":1}]}"));
		when(engine.supplierPerformance(any(), eq("SUP-1"))).thenReturn(json.readTree("{\"onTimeRate\":0.9}"));

		mockMvc.perform(as(post("/api/suppliers/search"), "planner").contentType(MediaType.APPLICATION_JSON)
						.content("{\"skuId\":\"SKU-001\",\"warehouseId\":\"W1\",\"quantity\":100}"))
				.andExpect(status().isOk()).andExpect(jsonPath("$.ranked[0].rank").value(1));
		mockMvc.perform(as(get("/api/suppliers/SUP-1/performance"), "finance"))
				.andExpect(status().isOk()).andExpect(jsonPath("$.onTimeRate").value(0.9));
		verify(engine).supplierPerformance(new Actor("pat", "finance"), "SUP-1");
	}

	@Test
	void supplierSearchIsForPlanningRolesOnly() throws Exception {
		mockMvc.perform(as(post("/api/suppliers/search"), "finance").contentType(MediaType.APPLICATION_JSON)
						.content("{\"skuId\":\"SKU-001\"}"))
				.andExpect(status().isForbidden()).andExpect(jsonPath("$.code").value("FORBIDDEN"));
		verify(engine, never()).searchSuppliers(any(), any());
	}

	@Test
	void engineFailuresKeepTheirCodeAndStatus() throws Exception {
		when(engine.searchSuppliers(any(), any()))
				.thenThrow(new MlServiceException(404, "UNKNOWN_WAREHOUSE", "unknown warehouse NOPE"));
		mockMvc.perform(as(post("/api/suppliers/search"), "planner").contentType(MediaType.APPLICATION_JSON)
						.content("{\"skuId\":\"SKU-001\",\"warehouseId\":\"NOPE\",\"quantity\":1}"))
				.andExpect(status().isNotFound()).andExpect(jsonPath("$.code").value("UNKNOWN_WAREHOUSE"));
	}

}
