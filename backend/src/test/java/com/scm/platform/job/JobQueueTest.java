package com.scm.platform.job;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;

import com.scm.platform.error.ApiException;
import com.scm.platform.error.RequestValidationException;
import com.scm.platform.mlservice.MlEngineClient;
import com.scm.platform.mlservice.MlServiceException;
import com.scm.platform.security.Actor;
import com.scm.platform.support.PostgresContainerConfig;
import java.time.Duration;
import java.util.ArrayList;
import java.util.List;
import java.util.UUID;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;
import java.util.concurrent.Future;
import java.util.concurrent.atomic.AtomicInteger;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

@SpringBootTest
@Import(PostgresContainerConfig.class)
class JobQueueTest {

	private static final Actor PLANNER = new Actor("pat", "planner");

	@Autowired
	private JobService jobs;

	@Autowired
	private JobWorker worker;

	@Autowired
	private JobRepository repository;

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

	private JsonNode optimizationPayload() {
		return json.readTree("{\"skuIds\":[\"SKU-001\"],\"horizonWeeks\":4}");
	}

	private Job reload(Job job) {
		return repository.find(job.id()).orElseThrow();
	}

	@Test
	void aSubmittedJobRunsAndKeepsItsDurableResult() {
		when(engine.optimize(any(), any())).thenReturn(json.readTree("{\"planId\":\"PLAN-001\",\"fillRate\":0.97}"));

		Job job = jobs.submit(PLANNER, JobType.OPTIMIZATION, null, optimizationPayload()).job();
		assertThat(job.status()).isEqualTo(JobStatus.QUEUED);

		assertThat(worker.runOnce()).isTrue();
		assertThat(worker.runOnce()).isFalse();

		Job done = reload(job);
		assertThat(done.status()).isEqualTo(JobStatus.SUCCEEDED);
		assertThat(done.result().path("planId").asString()).isEqualTo("PLAN-001");
		assertThat(done.attempts()).isEqualTo(1);
		assertThat(done.finishedAt()).isNotNull();
		assertThat(done.errorCode()).isNull();
	}

	@Test
	void theEngineIsCalledAsTheSubmittingUser() {
		when(engine.optimize(any(), any())).thenReturn(json.readTree("{}"));
		jobs.submit(PLANNER, JobType.OPTIMIZATION, null, optimizationPayload());
		worker.drain();
		org.mockito.Mockito.verify(engine).optimize(org.mockito.ArgumentMatchers.eq(PLANNER),
				org.mockito.ArgumentMatchers.eq(optimizationPayload()));
	}

	@Test
	void theSameRequestWithTheSameKeyIsNotQueuedTwice() {
		var first = jobs.submit(PLANNER, JobType.OPTIMIZATION, "key-1", optimizationPayload());
		// same request, keys in another order
		var second = jobs.submit(PLANNER, JobType.OPTIMIZATION, "key-1",
				json.readTree("{\"horizonWeeks\":4,\"skuIds\":[\"SKU-001\"]}"));

		assertThat(first.created()).isTrue();
		assertThat(second.created()).isFalse();
		assertThat(second.job().id()).isEqualTo(first.job().id());
		assertThat(jdbc.sql("SELECT count(*) FROM job").query(Integer.class).single()).isEqualTo(1);
	}

	@Test
	void aKeyReusedForADifferentRequestIsAConflict() {
		jobs.submit(PLANNER, JobType.OPTIMIZATION, "key-1", optimizationPayload());
		assertThatThrownBy(() -> jobs.submit(PLANNER, JobType.OPTIMIZATION, "key-1",
				json.readTree("{\"skuIds\":[\"SKU-002\"]}")))
				.isInstanceOfSatisfying(ApiException.class, ex -> {
					assertThat(ex.status()).isEqualTo(409);
					assertThat(ex.code()).isEqualTo("IDEMPOTENCY_CONFLICT");
				});
	}

	@Test
	void keysAreScopedToTheUser() {
		var mine = jobs.submit(PLANNER, JobType.OPTIMIZATION, "shared-key", optimizationPayload());
		var theirs = jobs.submit(new Actor("sam", "planner"), JobType.OPTIMIZATION, "shared-key",
				optimizationPayload());
		assertThat(theirs.created()).isTrue();
		assertThat(theirs.job().id()).isNotEqualTo(mine.job().id());
	}

	@Test
	void withoutAKeyEverySubmissionIsANewJob() {
		jobs.submit(PLANNER, JobType.OPTIMIZATION, null, optimizationPayload());
		jobs.submit(PLANNER, JobType.OPTIMIZATION, null, optimizationPayload());
		assertThat(jdbc.sql("SELECT count(*) FROM job").query(Integer.class).single()).isEqualTo(2);
	}

	@Test
	void malformedPayloadsAreRejectedAtSubmission() {
		assertThatThrownBy(() -> jobs.submit(PLANNER, JobType.OPTIMIZATION, null, json.readTree("{\"skuIds\":[]}")))
				.isInstanceOfSatisfying(RequestValidationException.class,
						ex -> assertThat(ex.violations()).extracting("field").containsExactly("skuIds"));
		assertThatThrownBy(() -> jobs.submit(PLANNER, JobType.OPTIMIZATION, null, json.readTree("[1]")))
				.isInstanceOf(ApiException.class);
		assertThatThrownBy(() -> jobs.submit(PLANNER, JobType.FORECAST, null, json.readTree("{\"skuId\":\"S\"}")))
				.isInstanceOf(RequestValidationException.class);
		assertThat(jdbc.sql("SELECT count(*) FROM job").query(Integer.class).single()).isZero();
	}

	@Test
	void transientEngineFailuresAreRetriedUntilTheyPass() {
		when(engine.optimize(any(), any()))
				.thenThrow(new MlServiceException(503, "ML_SERVICE_UNAVAILABLE", "down"))
				.thenThrow(new MlServiceException(503, "ML_SERVICE_UNAVAILABLE", "down"))
				.thenReturn(json.readTree("{\"planId\":\"PLAN-007\"}"));

		Job job = jobs.submit(PLANNER, JobType.OPTIMIZATION, null, optimizationPayload()).job();

		assertThat(worker.drain()).isEqualTo(3);
		Job done = reload(job);
		assertThat(done.status()).isEqualTo(JobStatus.SUCCEEDED);
		assertThat(done.attempts()).isEqualTo(3);
		assertThat(done.lastError()).isNull();
	}

	@Test
	void aJobThatKeepsFailingEndsInTheFailedStateWithTheEnginesCode() {
		when(engine.optimize(any(), any())).thenThrow(new MlServiceException(503, "ML_SERVICE_UNAVAILABLE", "down"));

		Job job = jobs.submit(PLANNER, JobType.OPTIMIZATION, null, optimizationPayload()).job();

		assertThat(worker.drain()).isEqualTo(3);
		Job failed = reload(job);
		assertThat(failed.status()).isEqualTo(JobStatus.FAILED);
		assertThat(failed.attempts()).isEqualTo(failed.maxAttempts());
		assertThat(failed.errorCode()).isEqualTo("ML_SERVICE_UNAVAILABLE");
		assertThat(failed.result()).isNull();
	}

	@Test
	void requestErrorsFailImmediatelyWithoutRetry() {
		when(engine.optimize(any(), any())).thenThrow(new MlServiceException(404, "UNKNOWN_SKU", "unknown SKU NOPE"));

		Job job = jobs.submit(PLANNER, JobType.OPTIMIZATION, null, optimizationPayload()).job();

		assertThat(worker.drain()).isEqualTo(1);
		Job failed = reload(job);
		assertThat(failed.status()).isEqualTo(JobStatus.FAILED);
		assertThat(failed.attempts()).isEqualTo(1);
		assertThat(failed.errorCode()).isEqualTo("UNKNOWN_SKU");
		assertThat(failed.errorMessage()).isEqualTo("unknown SKU NOPE");
	}

	@Test
	void unexpectedErrorsFailTheJobWithoutLeakingDetails() {
		when(engine.optimize(any(), any())).thenThrow(new IllegalStateException("secret internals"));

		Job job = jobs.submit(PLANNER, JobType.OPTIMIZATION, null, optimizationPayload()).job();
		worker.drain();

		Job failed = reload(job);
		assertThat(failed.status()).isEqualTo(JobStatus.FAILED);
		assertThat(failed.errorCode()).isEqualTo("INTERNAL_ERROR");
		assertThat(failed.errorMessage()).doesNotContain("secret");
	}

	@Test
	void aJobHeldByACrashedWorkerIsTakenOverAfterItsLeaseExpires() throws Exception {
		Job job = jobs.submit(PLANNER, JobType.OPTIMIZATION, null, optimizationPayload()).job();

		assertThat(repository.claim("crashed-worker", Duration.ofMillis(100))).isPresent();
		assertThat(repository.claim("other-worker", Duration.ofSeconds(60))).isEmpty(); // still leased
		Thread.sleep(250);

		var takenOver = repository.claim("other-worker", Duration.ofSeconds(60));
		assertThat(takenOver).isPresent();
		assertThat(takenOver.get().id()).isEqualTo(job.id());
		assertThat(takenOver.get().attempts()).isEqualTo(2);

		// the crashed worker coming back cannot overwrite the new owner's outcome
		assertThat(repository.succeed(job.id(), "crashed-worker", json.readTree("{}"))).isFalse();
		assertThat(repository.succeed(job.id(), "other-worker", json.readTree("{\"ok\":true}"))).isTrue();
		assertThat(reload(job).status()).isEqualTo(JobStatus.SUCCEEDED);
	}

	@Test
	void aLeaseThatExpiresWithNoAttemptsLeftFailsTheJob() throws Exception {
		Job job = jobs.submit(PLANNER, JobType.OPTIMIZATION, null, optimizationPayload()).job();
		for (int attempt = 1; attempt <= job.maxAttempts(); attempt++) {
			assertThat(repository.claim("worker-" + attempt, Duration.ofMillis(50))).isPresent();
			Thread.sleep(150);
		}

		assertThat(repository.claim("last-worker", Duration.ofSeconds(60))).isEmpty();
		Job failed = reload(job);
		assertThat(failed.status()).isEqualTo(JobStatus.FAILED);
		assertThat(failed.errorCode()).isEqualTo("LEASE_EXPIRED");
	}

	@Test
	void aRetryWaitsForItsBackoffBeforeRunningAgain() {
		Job job = jobs.submit(PLANNER, JobType.OPTIMIZATION, null, optimizationPayload()).job();
		repository.claim("w", Duration.ofSeconds(60));

		assertThat(repository.requeue(job.id(), "w", "ML_SERVICE_UNAVAILABLE: down", Duration.ofMinutes(5))).isTrue();

		assertThat(repository.claim("w", Duration.ofSeconds(60))).isEmpty();
		Job waiting = reload(job);
		assertThat(waiting.status()).isEqualTo(JobStatus.QUEUED);
		assertThat(waiting.lastError()).contains("down");
		assertThat(waiting.runAfter()).isAfter(waiting.createdAt().plusSeconds(200));
	}

	@Test
	void concurrentWorkersRunEveryJobExactlyOnce() throws Exception {
		AtomicInteger runs = new AtomicInteger();
		when(engine.optimize(any(), any())).thenAnswer(invocation -> {
			runs.incrementAndGet();
			return json.readTree("{}");
		});
		List<UUID> ids = new ArrayList<>();
		for (int i = 0; i < 24; i++) {
			ids.add(jobs.submit(PLANNER, JobType.OPTIMIZATION, "job-" + i, optimizationPayload()).job().id());
		}

		ExecutorService pool = Executors.newFixedThreadPool(6);
		try {
			List<Future<Integer>> futures = new ArrayList<>();
			for (int i = 0; i < 6; i++) {
				futures.add(pool.submit(worker::drain));
			}
			int total = 0;
			for (Future<Integer> future : futures) {
				total += future.get();
			}
			assertThat(total).isEqualTo(24);
		}
		finally {
			pool.shutdownNow();
		}
		assertThat(runs.get()).isEqualTo(24);
		assertThat(jdbc.sql("SELECT count(*) FROM job WHERE status = 'SUCCEEDED' AND attempts = 1")
				.query(Integer.class).single()).isEqualTo(24);
	}

	@Test
	void batchEvaluationSummarisesEachTaskAndSurvivesOneBeingRejected() {
		when(engine.runAgentTask(any(), org.mockito.ArgumentMatchers.eq("forecast SKU-001")))
				.thenReturn(json.readTree("{\"taskId\":\"TASK-1\",\"status\":\"COMPLETED\",\"violations\":[]}"));
		when(engine.runAgentTask(any(), org.mockito.ArgumentMatchers.eq("bad")))
				.thenThrow(new MlServiceException(422, "VALIDATION_FAILED", "nope"));

		Job job = jobs.submit(PLANNER, JobType.BATCH_EVALUATION, null,
				json.readTree("{\"tasks\":[\"forecast SKU-001\",\"bad\"]}")).job();
		worker.drain();

		Job done = reload(job);
		assertThat(done.status()).isEqualTo(JobStatus.SUCCEEDED);
		assertThat(done.result().path("total").asInt()).isEqualTo(2);
		assertThat(done.result().path("handled").asInt()).isEqualTo(1);
		assertThat(done.result().path("items").get(0).path("taskId").asString()).isEqualTo("TASK-1");
		assertThat(done.result().path("items").get(1).path("errorCode").asString()).isEqualTo("VALIDATION_FAILED");
	}

	@Test
	void jobsArePrivateToTheirSubmitterAndAdmins() {
		Job job = jobs.submit(PLANNER, JobType.OPTIMIZATION, null, optimizationPayload()).job();

		assertThat(jobs.get(PLANNER, job.id()).id()).isEqualTo(job.id());
		assertThat(jobs.get(new Actor("root", "admin"), job.id()).id()).isEqualTo(job.id());
		assertThatThrownBy(() -> jobs.get(new Actor("sam", "planner"), job.id()))
				.isInstanceOfSatisfying(ApiException.class, ex -> assertThat(ex.status()).isEqualTo(404));
		assertThat(jobs.recent(new Actor("sam", "planner"), 10)).isEmpty();
		assertThat(jobs.recent(PLANNER, 10)).hasSize(1);
	}

}
