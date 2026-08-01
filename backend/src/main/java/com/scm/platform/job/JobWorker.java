package com.scm.platform.job;

import com.scm.platform.config.ScmProperties;
import com.scm.platform.mlservice.MlServiceException;
import java.time.Duration;
import java.util.EnumMap;
import java.util.List;
import java.util.Map;
import java.util.Optional;
import java.util.UUID;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Component;
import tools.jackson.databind.JsonNode;

/**
 * Claims and runs queued jobs. {@link #runOnce()} is the unit of work; {@link JobWorkerScheduler} calls it
 * on a timer, and tests call it directly so they never wait on a poll.
 */
@Component
public class JobWorker {

	private static final Logger log = LoggerFactory.getLogger(JobWorker.class);

	private static final int MAX_MESSAGE = 500;

	private final JobRepository repository;

	private final Map<JobType, JobHandler> handlers = new EnumMap<>(JobType.class);

	private final Duration lease;

	private final Duration retryBackoff;

	private final String workerId = "worker-" + UUID.randomUUID();

	public JobWorker(JobRepository repository, List<JobHandler> handlers, ScmProperties properties) {
		this.repository = repository;
		handlers.forEach(handler -> this.handlers.put(handler.type(), handler));
		this.lease = properties.jobs().lease();
		this.retryBackoff = properties.jobs().retryBackoff();
	}

	/** Runs the next runnable job, if any. Returns whether a job was claimed. */
	public boolean runOnce() {
		Optional<Job> claimed = repository.claim(workerId, lease);
		if (claimed.isEmpty()) {
			return false;
		}
		Job job = claimed.get();
		try {
			JobHandler handler = handlers.get(job.type());
			if (handler == null) {
				fail(job, "NO_HANDLER", "no handler is registered for " + job.type());
				return true;
			}
			JsonNode result = handler.handle(job);
			if (!repository.succeed(job.id(), workerId, result)) {
				log.warn("job {} finished but its lease was lost; the new owner's outcome stands", job.id());
			}
		}
		catch (MlServiceException ex) {
			if (ex.status() >= 500 && job.attempts() < job.maxAttempts()) {
				retry(job, ex.code() + ": " + ex.getMessage());
			}
			else {
				fail(job, ex.code(), ex.getMessage());
			}
		}
		catch (RuntimeException ex) {
			log.error("job {} failed unexpectedly", job.id(), ex);
			fail(job, "INTERNAL_ERROR", "unexpected error while running the job");
		}
		return true;
	}

	/** Runs jobs until none is runnable; returns how many ran. */
	public int drain() {
		int ran = 0;
		while (runOnce()) {
			ran++;
		}
		return ran;
	}

	private void retry(Job job, String reason) {
		Duration delay = retryBackoff.multipliedBy(1L << Math.min(job.attempts() - 1, 20));
		log.warn("job {} attempt {}/{} failed ({}); retrying in {}", job.id(), job.attempts(), job.maxAttempts(),
				reason, delay);
		repository.requeue(job.id(), workerId, truncate(reason), delay);
	}

	private void fail(Job job, String code, String message) {
		log.warn("job {} failed permanently: {} {}", job.id(), code, message);
		repository.fail(job.id(), workerId, code, truncate(message));
	}

	private static String truncate(String text) {
		return text == null || text.length() <= MAX_MESSAGE ? text : text.substring(0, MAX_MESSAGE);
	}

}
