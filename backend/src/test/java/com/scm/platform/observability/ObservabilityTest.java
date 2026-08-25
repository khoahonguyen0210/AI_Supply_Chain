package com.scm.platform.observability;

import static org.assertj.core.api.Assertions.assertThat;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.scm.platform.job.JobService;
import com.scm.platform.job.JobType;
import com.scm.platform.job.JobWorker;
import com.scm.platform.mlservice.MlEngineClient;
import com.scm.platform.mlservice.MlServiceException;
import com.scm.platform.security.Actor;
import com.scm.platform.support.PostgresContainerConfig;
import com.scm.platform.support.TestAuth;
import com.scm.platform.support.TestData;
import io.micrometer.core.instrument.MeterRegistry;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import tools.jackson.databind.json.JsonMapper;

@SpringBootTest
@AutoConfigureMockMvc
@Import(PostgresContainerConfig.class)
class ObservabilityTest {

	private static final Actor PLANNER = new Actor("pat", "planner");

	@Autowired
	private MockMvc mockMvc;

	@Autowired
	private JdbcClient jdbc;

	@Autowired
	private JobService jobs;

	@Autowired
	private JobWorker worker;

	@Autowired
	private MeterRegistry registry;

	@Autowired
	private RequestMetricsFilter requests;

	@Autowired
	private JobMetrics jobMetrics;

	@Autowired
	private JsonMapper json;

	@MockitoBean
	private MlEngineClient engine;

	@BeforeEach
	void reset() {
		TestData.reset(jdbc);
	}

	private static MockHttpServletRequestBuilder as(MockHttpServletRequestBuilder request, String role) {
		return TestAuth.as(request, "u", role);
	}

	private void submitOptimization(String key) {
		jobs.submit(PLANNER, JobType.OPTIMIZATION, key, json.readTree("{\"skuIds\":[\"SKU-001\"]}"));
	}

	private double gauge(String status) {
		return registry.get("scm.jobs").tag("status", status).gauge().value();
	}

	@Test
	void queueDepthAndOutcomesAreVisibleAsMetrics() throws Exception {
		when(engine.optimize(any(), any())).thenReturn(json.readTree("{}"));
		submitOptimization("a");
		submitOptimization("b");
		Thread.sleep(1100); // gauges refresh the database counts at most once a second
		assertThat(gauge("queued")).isEqualTo(2);
		assertThat(registry.get("scm.jobs.oldest.queued.seconds").gauge().value()).isGreaterThanOrEqualTo(0);

		worker.drain();
		Thread.sleep(1100);

		assertThat(gauge("queued")).isZero();
		assertThat(gauge("succeeded")).isEqualTo(2);
		assertThat(jobMetrics.attempts(JobType.OPTIMIZATION, "succeeded")).isGreaterThanOrEqualTo(2);
		assertThat(registry.get("scm.jobs.duration").tag("type", "optimization").timer().count())
				.isGreaterThanOrEqualTo(2);
		assertThat(jobMetrics.utilization()).isBetween(0.0, 1.0);
	}

	@Test
	void failedAndRetriedAttemptsAreCountedByOutcome() {
		when(engine.optimize(any(), any())).thenThrow(new MlServiceException(503, "ML_SERVICE_UNAVAILABLE", "down"));
		long failedBefore = jobMetrics.attempts(JobType.OPTIMIZATION, "failed");
		long retriedBefore = jobMetrics.attempts(JobType.OPTIMIZATION, "retried");
		submitOptimization("x");

		worker.drain(); // attempts 1 and 2 are retried, attempt 3 fails the job

		assertThat(jobMetrics.attempts(JobType.OPTIMIZATION, "retried") - retriedBefore).isEqualTo(2);
		assertThat(jobMetrics.attempts(JobType.OPTIMIZATION, "failed") - failedBefore).isEqualTo(1);
	}

	@Test
	void everyApiRequestIsTimedAndCountedByOutcome() throws Exception {
		long total = requests.total();
		long clientErrors = requests.clientErrors();
		mockMvc.perform(get("/api/health")).andExpect(status().isOk());
		mockMvc.perform(get("/api/skus")).andExpect(status().isUnauthorized());

		assertThat(requests.total() - total).isEqualTo(2);
		assertThat(requests.clientErrors() - clientErrors).isEqualTo(1);
		assertThat(requests.percentile(0.95)).isGreaterThanOrEqualTo(requests.percentile(0.5));
		assertThat(registry.get("scm.api.requests").tag("status", "2xx-3xx").counter().count())
				.isGreaterThanOrEqualTo(1);
	}

	@Test
	void theSummaryGivesAdminsLatencyErrorRateAndQueueState() throws Exception {
		mockMvc.perform(get("/api/health"));
		mockMvc.perform(as(get("/api/ops/summary"), "admin"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.api.requests").isNumber())
				.andExpect(jsonPath("$.api.p95Millis").isNumber())
				.andExpect(jsonPath("$.api.errorRate").isNumber())
				.andExpect(jsonPath("$.api.requestsPerSecond").isNumber())
				.andExpect(jsonPath("$.queue.byStatus.QUEUED").isNumber())
				.andExpect(jsonPath("$.queue.workerUtilization").isNumber())
				.andExpect(jsonPath("$.queue.meanDurationMillis.OPTIMIZATION").isNumber());
	}

	@Test
	void aiTelemetryIsRelayedFromTheEngineToAdminsOnly() throws Exception {
		when(engine.telemetry()).thenReturn(json.readTree(
				"{\"runtime\":{\"agent\":{\"count\":3}},\"quality\":{\"rag\":{\"available\":true}}}"));
		mockMvc.perform(as(get("/api/ops/ai"), "admin"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.runtime.agent.count").value(3))
				.andExpect(jsonPath("$.quality.rag.available").value(true));
		mockMvc.perform(as(get("/api/ops/ai"), "finance")).andExpect(status().isForbidden());
	}

	@Test
	void theSummaryIsForAdminsOnly() throws Exception {
		mockMvc.perform(as(get("/api/ops/summary"), "planner")).andExpect(status().isForbidden());
	}

}
