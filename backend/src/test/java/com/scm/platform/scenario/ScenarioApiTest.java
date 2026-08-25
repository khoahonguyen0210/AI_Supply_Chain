package com.scm.platform.scenario;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.scm.platform.job.JobWorker;
import com.scm.platform.mlservice.MlEngineClient;
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
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

@SpringBootTest
@AutoConfigureMockMvc
@Import(PostgresContainerConfig.class)
class ScenarioApiTest {

	private static final String CREATE = "{\"name\":\"Demand +50%\",\"scenarioType\":\"DEMAND_SHOCK\","
			+ "\"parameters\":{\"factor\":1.5}}";

	private static final String RUN = "{\"plan\":{\"skuIds\":[\"SKU-001\"],\"horizonWeeks\":4}}";

	@Autowired
	private MockMvc mockMvc;

	@Autowired
	private JdbcClient jdbc;

	@Autowired
	private JsonMapper json;

	@Autowired
	private JobWorker worker;

	@MockitoBean
	private MlEngineClient engine;

	@BeforeEach
	void reset() {
		TestData.reset(jdbc);
	}

	private static MockHttpServletRequestBuilder as(MockHttpServletRequestBuilder request, String role) {
		return TestAuth.as(request, "pat", role);
	}

	private String createScenario() throws Exception {
		String body = mockMvc.perform(as(post("/api/scenarios"), "planner").contentType(MediaType.APPLICATION_JSON)
						.content(CREATE))
				.andExpect(status().isCreated())
				.andReturn().getResponse().getContentAsString();
		return json.readTree(body).path("scenarioId").asString();
	}

	@Test
	void aScenarioDefinitionIsSavedAndListed() throws Exception {
		String id = createScenario();

		mockMvc.perform(as(get("/api/scenarios/" + id), "finance"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.name").value("Demand +50%"))
				.andExpect(jsonPath("$.scenarioType").value("DEMAND_SHOCK"))
				.andExpect(jsonPath("$.parameters.factor").value(1.5));
		mockMvc.perform(as(get("/api/scenarios"), "planner")).andExpect(jsonPath("$.length()").value(1));
		mockMvc.perform(as(get("/api/scenarios/SCN-NOPE"), "planner"))
				.andExpect(status().isNotFound()).andExpect(jsonPath("$.code").value("UNKNOWN_SCENARIO"));
	}

	@Test
	void invalidDefinitionsAreRejected() throws Exception {
		mockMvc.perform(as(post("/api/scenarios"), "planner").contentType(MediaType.APPLICATION_JSON)
						.content("{\"name\":\"\",\"scenarioType\":\"DEMAND_SHOCK\"}"))
				.andExpect(status().isBadRequest()).andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));
		mockMvc.perform(as(post("/api/scenarios"), "planner").contentType(MediaType.APPLICATION_JSON)
						.content("{\"name\":\"x\",\"scenarioType\":\"METEOR\"}"))
				.andExpect(status().isBadRequest()).andExpect(jsonPath("$.code").value("MALFORMED_REQUEST"));
		mockMvc.perform(as(post("/api/scenarios"), "finance").contentType(MediaType.APPLICATION_JSON)
						.content(CREATE))
				.andExpect(status().isForbidden());
	}

	@Test
	void aRunIsAnAsyncJobWhoseResultIsTheEnginesComparison() throws Exception {
		when(engine.runScenario(any(), any())).thenReturn(json.readTree("{\"scenario\":{\"resilienceCost\":1200}}"));
		String id = createScenario();

		String accepted = mockMvc.perform(as(post("/api/scenarios/" + id + "/runs"), "planner")
						.contentType(MediaType.APPLICATION_JSON).content(RUN))
				.andExpect(status().isAccepted())
				.andExpect(jsonPath("$.type").value("SCENARIO"))
				.andReturn().getResponse().getContentAsString();
		String jobId = json.readTree(accepted).path("id").asString();

		worker.drain();

		mockMvc.perform(as(get("/api/jobs/" + jobId), "planner"))
				.andExpect(jsonPath("$.status").value("SUCCEEDED"))
				.andExpect(jsonPath("$.result.scenario.resilienceCost").value(1200));

		org.mockito.ArgumentCaptor<JsonNode> request = org.mockito.ArgumentCaptor.forClass(JsonNode.class);
		org.mockito.Mockito.verify(engine).runScenario(any(), request.capture());
		assertThat(request.getValue().path("scenarioType").asString()).isEqualTo("DEMAND_SHOCK");
		assertThat(request.getValue().path("parameters").path("factor").asDouble()).isEqualTo(1.5);
		assertThat(request.getValue().path("plan").path("skuIds").get(0).asString()).isEqualTo("SKU-001");
	}

	@Test
	void replayingARunWithTheSameKeyDoesNotQueueItTwice() throws Exception {
		String id = createScenario();
		MockHttpServletRequestBuilder first = as(post("/api/scenarios/" + id + "/runs"), "planner")
				.header("Idempotency-Key", "k1").contentType(MediaType.APPLICATION_JSON).content(RUN);
		mockMvc.perform(first).andExpect(status().isAccepted());
		mockMvc.perform(as(post("/api/scenarios/" + id + "/runs"), "planner").header("Idempotency-Key", "k1")
						.contentType(MediaType.APPLICATION_JSON).content(RUN))
				.andExpect(status().isOk());
		assertThat(jdbc.sql("SELECT count(*) FROM job").query(Integer.class).single()).isEqualTo(1);
	}

	@Test
	void runningAnUnknownScenarioIs404AndNothingIsQueued() throws Exception {
		mockMvc.perform(as(post("/api/scenarios/SCN-NOPE/runs"), "planner").contentType(MediaType.APPLICATION_JSON)
						.content(RUN))
				.andExpect(status().isNotFound());
		assertThat(jdbc.sql("SELECT count(*) FROM job").query(Integer.class).single()).isZero();
	}

}
