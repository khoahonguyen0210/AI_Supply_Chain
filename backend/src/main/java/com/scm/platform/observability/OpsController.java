package com.scm.platform.observability;

import com.scm.platform.audit.AuditService;
import com.scm.platform.job.JobStatus;
import com.scm.platform.job.JobType;
import com.scm.platform.mlservice.MlEngineClient;
import com.scm.platform.security.Actor;
import com.scm.platform.security.Roles;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Map;
import java.util.Set;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.JsonNode;

@RestController
@RequestMapping("/api/ops")
public class OpsController {

	private static final Set<String> ADMINS = Set.of(Roles.ADMIN);

	private final RequestMetricsFilter requests;

	private final JobMetrics jobs;

	private final MlEngineClient engine;

	private final AuditService audit;

	public OpsController(RequestMetricsFilter requests, JobMetrics jobs, MlEngineClient engine, AuditService audit) {
		this.requests = requests;
		this.jobs = jobs;
		this.engine = engine;
		this.audit = audit;
	}

	public record ApiStats(long requests, long serverErrors, long clientErrors, double errorRate,
			double p50Millis, double p95Millis, double requestsPerSecond, long uptimeSeconds) {
	}

	public record QueueStats(Map<JobStatus, Long> byStatus, double oldestQueuedSeconds, double workerUtilization,
			Map<String, Double> meanDurationMillis, Map<String, Long> failedAttempts) {
	}

	public record Summary(ApiStats api, QueueStats queue) {
	}

	@GetMapping("/summary")
	public Summary summary(Actor actor) {
		Roles.require(actor, ADMINS);
		long total = requests.total();
		long seconds = Math.max(1, jobs.uptime().toSeconds());
		ApiStats api = new ApiStats(total, requests.serverErrors(), requests.clientErrors(),
				total == 0 ? 0 : (double) requests.serverErrors() / total, requests.percentile(0.5).toNanos() / 1e6,
				requests.percentile(0.95).toNanos() / 1e6, (double) total / seconds, seconds);
		Map<String, Double> means = new LinkedHashMap<>();
		Map<String, Long> failed = new LinkedHashMap<>();
		for (JobType type : JobType.values()) {
			means.put(type.name(), jobs.meanDuration(type).toNanos() / 1e6);
			failed.put(type.name(), jobs.attempts(type, "failed"));
		}
		QueueStats queue = new QueueStats(jobs.counts(), jobs.oldestQueuedSeconds(), jobs.utilization(), means,
				failed);
		return new Summary(api, queue);
	}

	@GetMapping("/audit")
	public List<AuditService.Entry> audit(Actor actor, @RequestParam(required = false) String user,
			@RequestParam(required = false) AuditService.Outcome outcome,
			@RequestParam(defaultValue = "100") int limit) {
		Roles.require(actor, ADMINS);
		return audit.recent(user, outcome, limit);
	}

	@GetMapping("/ai")
	public JsonNode ai(Actor actor) {
		Roles.require(actor, ADMINS);
		return engine.telemetry();
	}

}
