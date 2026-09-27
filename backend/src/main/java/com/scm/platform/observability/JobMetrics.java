package com.scm.platform.observability;

import com.scm.platform.job.JobRepository;
import com.scm.platform.job.JobStatus;
import com.scm.platform.job.JobType;
import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.Gauge;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import java.time.Duration;
import java.util.EnumMap;
import java.util.Map;
import java.util.concurrent.TimeUnit;
import java.util.concurrent.atomic.AtomicLong;
import org.springframework.stereotype.Component;

@Component
public class JobMetrics {

	private final JobRepository repository;

	private final MeterRegistry registry;

	private final Map<JobType, Timer> durations = new EnumMap<>(JobType.class);

	private final AtomicLong busyNanos = new AtomicLong();

	private final long startedNanos = System.nanoTime();

	private volatile Map<JobStatus, Long> cachedCounts = Map.of();

	private volatile long cachedAtNanos;

	public JobMetrics(JobRepository repository, MeterRegistry registry) {
		this.repository = repository;
		this.registry = registry;
		for (JobStatus status : JobStatus.values()) {
			Gauge.builder("scm.jobs", () -> counts().getOrDefault(status, 0L))
					.description("Jobs by status").tag("status", status.name().toLowerCase()).register(registry);
		}
		Gauge.builder("scm.jobs.oldest.queued.seconds", repository::oldestQueuedAgeSeconds)
				.description("Age of the oldest job waiting to run").register(registry);
		Gauge.builder("scm.jobs.worker.utilization", this::utilization)
				.description("Share of this instance's uptime its worker spent running jobs").register(registry);
		for (JobType type : JobType.values()) {
			durations.put(type, Timer.builder("scm.jobs.duration").tag("type", type.name().toLowerCase())
					.description("Time to run a job attempt").publishPercentiles(0.5, 0.95).register(registry));
		}
	}

	/** Refreshed at most once a second so a scrape storm does not hammer the database. */
	public Map<JobStatus, Long> counts() {
		long now = System.nanoTime();
		if (now - cachedAtNanos > TimeUnit.SECONDS.toNanos(1) || cachedCounts.isEmpty()) {
			cachedCounts = repository.countsByStatus();
			cachedAtNanos = now;
		}
		return cachedCounts;
	}

	public void attemptFinished(JobType type, String outcome, Duration elapsed) {
		durations.get(type).record(elapsed);
		busyNanos.addAndGet(elapsed.toNanos());
		Counter.builder("scm.jobs.attempts").tag("type", type.name().toLowerCase()).tag("outcome", outcome)
				.register(registry).increment();
	}

	public double oldestQueuedSeconds() {
		return repository.oldestQueuedAgeSeconds();
	}

	public double utilization() {
		long elapsed = System.nanoTime() - startedNanos;
		return elapsed <= 0 ? 0 : Math.min(1.0, (double) busyNanos.get() / elapsed);
	}

	public Duration uptime() {
		return Duration.ofNanos(System.nanoTime() - startedNanos);
	}

	public Duration meanDuration(JobType type) {
		Timer timer = durations.get(type);
		return timer.count() == 0 ? Duration.ZERO : Duration.ofNanos((long) timer.mean(TimeUnit.NANOSECONDS));
	}

	public long attempts(JobType type, String outcome) {
		Counter counter = registry.find("scm.jobs.attempts").tag("type", type.name().toLowerCase())
				.tag("outcome", outcome).counter();
		return counter == null ? 0 : (long) counter.count();
	}

}
