package com.scm.platform.job;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.scm.platform.mlservice.MlEngineClient;
import com.scm.platform.support.PostgresContainerConfig;
import com.scm.platform.support.TestAuth;
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
class JobControllerTest {

	private static final String BODY = "{\"type\":\"OPTIMIZATION\",\"payload\":{\"skuIds\":[\"SKU-001\"]}}";

	@Autowired
	private MockMvc mockMvc;

	@Autowired
	private JobWorker worker;

	@Autowired
	private JdbcClient jdbc;

	@Autowired
	private JsonMapper json;

	@MockitoBean
	private MlEngineClient engine;

	@BeforeEach
	void emptyQueue() {
		jdbc.sql("TRUNCATE job").update();
	}

	private static MockHttpServletRequestBuilder as(MockHttpServletRequestBuilder request, String user, String role) {
		return TestAuth.as(request, user, role);
	}

	private String submit(String key) throws Exception {
		MockHttpServletRequestBuilder request = as(post("/api/jobs"), "pat", "planner")
				.contentType(MediaType.APPLICATION_JSON).content(BODY);
		if (key != null) {
			request.header("Idempotency-Key", key);
		}
		String response = mockMvc.perform(request).andReturn().getResponse().getContentAsString();
		return json.readTree(response).path("id").asString();
	}

	@Test
	void submitReturns202WithALocationThenPollingShowsTheResult() throws Exception {
		when(engine.optimize(any(), any())).thenReturn(json.readTree("{\"planId\":\"PLAN-001\"}"));

		String response = mockMvc.perform(as(post("/api/jobs"), "pat", "planner")
						.contentType(MediaType.APPLICATION_JSON).content(BODY))
				.andExpect(status().isAccepted())
				.andExpect(jsonPath("$.status").value("QUEUED"))
				.andExpect(jsonPath("$.type").value("OPTIMIZATION"))
				.andExpect(header().exists("Location"))
				.andReturn().getResponse().getContentAsString();
		String id = json.readTree(response).path("id").asString();

		mockMvc.perform(as(get("/api/jobs/" + id), "pat", "planner"))
				.andExpect(status().isOk()).andExpect(jsonPath("$.status").value("QUEUED"));

		worker.drain();

		mockMvc.perform(as(get("/api/jobs/" + id), "pat", "planner"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.status").value("SUCCEEDED"))
				.andExpect(jsonPath("$.result.planId").value("PLAN-001"))
				.andExpect(jsonPath("$.attempts").value(1));
	}

	@Test
	void replayingAnIdempotentSubmissionReturns200WithTheSameJob() throws Exception {
		String first = submit("abc");
		String replay = mockMvc.perform(as(post("/api/jobs"), "pat", "planner").header("Idempotency-Key", "abc")
						.contentType(MediaType.APPLICATION_JSON).content(BODY))
				.andExpect(status().isOk())
				.andReturn().getResponse().getContentAsString();
		org.assertj.core.api.Assertions.assertThat(json.readTree(replay).path("id").asString()).isEqualTo(first);
	}

	@Test
	void aReusedKeyWithADifferentRequestIs409() throws Exception {
		submit("abc");
		mockMvc.perform(as(post("/api/jobs"), "pat", "planner").header("Idempotency-Key", "abc")
						.contentType(MediaType.APPLICATION_JSON)
						.content("{\"type\":\"OPTIMIZATION\",\"payload\":{\"skuIds\":[\"SKU-009\"]}}"))
				.andExpect(status().isConflict())
				.andExpect(jsonPath("$.code").value("IDEMPOTENCY_CONFLICT"));
	}

	@Test
	void invalidSubmissionsAre400WithStructuredErrors() throws Exception {
		mockMvc.perform(as(post("/api/jobs"), "pat", "planner").contentType(MediaType.APPLICATION_JSON)
						.content("{\"type\":\"OPTIMIZATION\",\"payload\":{\"skuIds\":[]}}"))
				.andExpect(status().isBadRequest())
				.andExpect(jsonPath("$.code").value("VALIDATION_FAILED"))
				.andExpect(jsonPath("$.violations[0].field").value("skuIds"));
		mockMvc.perform(as(post("/api/jobs"), "pat", "planner").contentType(MediaType.APPLICATION_JSON)
						.content("{\"type\":\"NOPE\",\"payload\":{}}"))
				.andExpect(status().isBadRequest())
				.andExpect(jsonPath("$.code").value("MALFORMED_REQUEST"));
		mockMvc.perform(as(post("/api/jobs"), "pat", "planner").contentType(MediaType.APPLICATION_JSON)
						.content("{\"type\":\"OPTIMIZATION\"}"))
				.andExpect(status().isBadRequest())
				.andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));
	}

	@Test
	void requestsWithoutAnIdentityAre401() throws Exception {
		mockMvc.perform(post("/api/jobs").contentType(MediaType.APPLICATION_JSON).content(BODY))
				.andExpect(status().isUnauthorized())
				.andExpect(jsonPath("$.code").value("UNAUTHENTICATED"));
	}

	@Test
	void anotherUsersJobIsNotFound() throws Exception {
		String id = submit(null);
		mockMvc.perform(as(get("/api/jobs/" + id), "sam", "planner")).andExpect(status().isNotFound())
				.andExpect(jsonPath("$.code").value("UNKNOWN_JOB"));
		mockMvc.perform(as(get("/api/jobs/" + id), "root", "admin")).andExpect(status().isOk());
		mockMvc.perform(as(get("/api/jobs/not-a-uuid"), "pat", "planner")).andExpect(status().isBadRequest());
	}

	@Test
	void listShowsTheCallersRecentJobsNewestFirst() throws Exception {
		submit(null);
		String newest = submit(null);
		mockMvc.perform(as(get("/api/jobs"), "pat", "planner"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.length()").value(2))
				.andExpect(jsonPath("$[0].id").value(newest));
		mockMvc.perform(as(get("/api/jobs"), "sam", "planner")).andExpect(jsonPath("$.length()").value(0));
	}

}
