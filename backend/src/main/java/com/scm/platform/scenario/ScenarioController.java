package com.scm.platform.scenario;

import com.scm.platform.error.ApiException;
import com.scm.platform.job.JobController.JobView;
import com.scm.platform.job.JobService;
import com.scm.platform.job.JobType;
import com.scm.platform.security.Actor;
import com.scm.platform.security.Roles;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.time.Instant;
import java.util.List;
import java.util.Map;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

/**
 * Saved scenario definitions and their runs. Parameters are the engine's scenario contract and are
 * validated by the engine when a scenario runs; a run is an async {@code SCENARIO} job.
 */
@RestController
@RequestMapping("/api/scenarios")
public class ScenarioController {

	private final ScenarioRepository scenarios;

	private final JobService jobs;

	private final JsonMapper json;

	public ScenarioController(ScenarioRepository scenarios, JobService jobs, JsonMapper json) {
		this.scenarios = scenarios;
		this.jobs = jobs;
		this.json = json;
	}

	public record CreateScenarioRequest(@NotBlank @Size(max = 120) String name, @NotNull ScenarioType scenarioType,
			Map<String, Object> parameters) {
	}

	public record ScenarioView(String scenarioId, String name, ScenarioType scenarioType, JsonNode parameters,
			Instant createdAt) {
	}

	public record RunScenarioRequest(@NotNull JsonNode plan) {
	}

	public enum ScenarioType {
		DEMAND_SHOCK, SUPPLIER_OUTAGE, PRICE_SHOCK, CAPACITY_REDUCTION, LEAD_TIME_SHOCK,
		WAREHOUSE_CAPACITY_REDUCTION, TRANSPORT_COST_SHOCK
	}

	@PostMapping
	public ResponseEntity<ScenarioView> create(Actor actor, @Valid @RequestBody CreateScenarioRequest request) {
		Roles.require(actor, Roles.PLANNING);
		String id = "SCN-" + UUID.randomUUID().toString().substring(0, 8).toUpperCase();
		JsonNode parameters = json.valueToTree(request.parameters() == null ? Map.of() : request.parameters());
		scenarios.insert(id, request.name().strip(), request.scenarioType(), parameters);
		return ResponseEntity.status(HttpStatus.CREATED).header("Location", "/api/scenarios/" + id)
				.body(scenarios.find(id).orElseThrow());
	}

	@GetMapping
	public List<ScenarioView> list(Actor actor) {
		return scenarios.list();
	}

	@GetMapping("/{scenarioId}")
	public ScenarioView get(Actor actor, @PathVariable String scenarioId) {
		return scenarios.find(scenarioId)
				.orElseThrow(() -> ApiException.notFound("UNKNOWN_SCENARIO", "no scenario " + scenarioId));
	}

	/** Queues a run of the scenario against a plan spec; poll the returned job for the comparison. */
	@PostMapping("/{scenarioId}/runs")
	public ResponseEntity<JobView> run(Actor actor, @PathVariable String scenarioId,
			@RequestHeader(name = "Idempotency-Key", required = false) String idempotencyKey,
			@Valid @RequestBody RunScenarioRequest request) {
		Roles.require(actor, Roles.PLANNING);
		ScenarioView scenario = get(actor, scenarioId);
		ObjectNode payload = json.createObjectNode();
		payload.set("plan", request.plan());
		payload.put("scenarioType", scenario.scenarioType().name());
		payload.set("parameters", scenario.parameters());
		JobService.Submission submission = jobs.submit(actor, JobType.SCENARIO,
				idempotencyKey == null ? null : scenarioId + ":" + idempotencyKey, payload);
		return ResponseEntity.status(submission.created() ? HttpStatus.ACCEPTED : HttpStatus.OK)
				.header("Location", "/api/jobs/" + submission.job().id()).body(JobView.of(submission.job()));
	}

}
