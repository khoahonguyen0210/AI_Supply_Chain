package com.scm.platform.job;

import com.scm.platform.security.Actor;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import java.time.Instant;
import java.util.List;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.JsonNode;

/** Submit long-running work and poll it: 202 with a job to poll, then GET until it is SUCCEEDED or FAILED. */
@RestController
@RequestMapping("/api/jobs")
public class JobController {

	private final JobService jobs;

	public JobController(JobService jobs) {
		this.jobs = jobs;
	}

	public record SubmitJobRequest(@NotNull JobType type, @NotNull JsonNode payload) {
	}

	public record JobView(UUID id, JobType type, JobStatus status, int attempts, int maxAttempts, JsonNode result,
			String errorCode, String errorMessage, String lastError, Instant createdAt, Instant startedAt,
			Instant finishedAt) {

		static JobView of(Job job) {
			return new JobView(job.id(), job.type(), job.status(), job.attempts(), job.maxAttempts(), job.result(),
					job.errorCode(), job.errorMessage(), job.lastError(), job.createdAt(), job.startedAt(),
					job.finishedAt());
		}
	}

	@PostMapping
	public ResponseEntity<JobView> submit(Actor actor,
			@RequestHeader(name = "Idempotency-Key", required = false) String idempotencyKey,
			@Valid @RequestBody SubmitJobRequest request) {
		JobService.Submission submission = jobs.submit(actor, request.type(), idempotencyKey, request.payload());
		HttpStatus status = submission.created() ? HttpStatus.ACCEPTED : HttpStatus.OK;
		return ResponseEntity.status(status).header("Location", "/api/jobs/" + submission.job().id())
				.body(JobView.of(submission.job()));
	}

	@GetMapping("/{id}")
	public JobView get(Actor actor, @PathVariable UUID id) {
		return JobView.of(jobs.get(actor, id));
	}

	@GetMapping
	public List<JobView> list(Actor actor, @RequestParam(defaultValue = "20") int limit) {
		return jobs.recent(actor, limit).stream().map(JobView::of).toList();
	}

}
