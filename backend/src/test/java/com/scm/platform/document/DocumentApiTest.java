package com.scm.platform.document;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.verify;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.scm.platform.mlservice.MlEngineClient;
import com.scm.platform.security.Actor;
import com.scm.platform.support.PostgresContainerConfig;
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
class DocumentApiTest {

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
		TestData.seedDocuments(jdbc);
	}

	private static MockHttpServletRequestBuilder as(MockHttpServletRequestBuilder request, String role) {
		return request.header("X-User-Id", "pat").header("X-User-Role", role);
	}

	@Test
	void aRoleOnlySeesTheDocumentsItMayRead() throws Exception {
		mockMvc.perform(as(get("/api/documents").param("asOf", "2024-12-30"), "planner"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.length()").value(1))
				.andExpect(jsonPath("$[0].documentId").value("POL-1"));
		mockMvc.perform(as(get("/api/documents").param("asOf", "2024-12-30"), "finance"))
				.andExpect(jsonPath("$.length()").value(1))
				.andExpect(jsonPath("$[0].documentId").value("CON-1"));
		mockMvc.perform(as(get("/api/documents").param("asOf", "2024-12-30"), "admin"))
				.andExpect(jsonPath("$.length()").value(2));
	}

	@Test
	void onlyTheVersionInForceIsListedUnlessSupersededOnesAreRequested() throws Exception {
		mockMvc.perform(as(get("/api/documents").param("asOf", "2024-12-30"), "planner"))
				.andExpect(jsonPath("$[0].version").value("v2")).andExpect(jsonPath("$[0].inForce").value(true));
		mockMvc.perform(as(get("/api/documents").param("asOf", "2024-12-30").param("includeSuperseded", "true"),
						"planner"))
				.andExpect(jsonPath("$.length()").value(2))
				.andExpect(jsonPath("$[1].version").value("v1")).andExpect(jsonPath("$[1].inForce").value(false));
		mockMvc.perform(as(get("/api/documents").param("asOf", "2024-03-01"), "planner"))
				.andExpect(jsonPath("$.length()").value(1)).andExpect(jsonPath("$[0].version").value("v1"));
	}

	@Test
	void filtersByTypeAndSupplier() throws Exception {
		mockMvc.perform(as(get("/api/documents").param("asOf", "2024-12-30").param("docType", "CONTRACT")
						.param("supplierId", "SUP-1"), "admin"))
				.andExpect(jsonPath("$.length()").value(1)).andExpect(jsonPath("$[0].documentId").value("CON-1"));
		mockMvc.perform(as(get("/api/documents").param("asOf", "2024-12-30").param("docType", "SLA"), "admin"))
				.andExpect(jsonPath("$.length()").value(0));
	}

	@Test
	void aDocumentIsReadWithItsContentOrNotFoundNeverForbidden() throws Exception {
		mockMvc.perform(as(get("/api/documents/POL-1").param("asOf", "2024-12-30"), "planner"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.summary.version").value("v2"))
				.andExpect(jsonPath("$.content").value("new text"));
		mockMvc.perform(as(get("/api/documents/POL-1").param("version", "v1"), "planner"))
				.andExpect(jsonPath("$.content").value("old text"));
		mockMvc.perform(as(get("/api/documents/CON-1"), "planner"))
				.andExpect(status().isNotFound()).andExpect(jsonPath("$.code").value("UNKNOWN_DOCUMENT"));
		mockMvc.perform(as(get("/api/documents/CON-1"), "finance")).andExpect(status().isOk());
	}

	@Test
	void questionsAreAnsweredByTheEngineAsTheCaller() throws Exception {
		when(engine.askDocuments(any(), any())).thenReturn(json.readTree("{\"status\":\"ANSWERED\"}"));
		mockMvc.perform(as(post("/api/documents/ask"), "planner").contentType(MediaType.APPLICATION_JSON)
						.content("{\"question\":\"What approval is needed?\"}"))
				.andExpect(status().isOk()).andExpect(jsonPath("$.status").value("ANSWERED"));
		verify(engine).askDocuments(any(Actor.class),
				org.mockito.ArgumentMatchers.eq(json.readTree("{\"question\":\"What approval is needed?\"}")));
		mockMvc.perform(as(post("/api/documents/ask"), "planner").contentType(MediaType.APPLICATION_JSON)
						.content("{\"question\":\"?\"}"))
				.andExpect(status().isBadRequest()).andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));
	}

}
