package com.scm.platform.job;

import com.scm.platform.config.ScmProperties;
import com.scm.platform.error.ApiError.FieldViolation;
import com.scm.platform.error.ApiException;
import com.scm.platform.error.RequestValidationException;
import com.scm.platform.security.Actor;
import jakarta.validation.ConstraintViolation;
import jakarta.validation.Validator;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;
import java.security.NoSuchAlgorithmException;
import java.util.ArrayList;
import java.util.HexFormat;
import java.util.List;
import java.util.Map;
import java.util.Set;
import java.util.TreeMap;
import java.util.UUID;
import org.springframework.stereotype.Service;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ObjectNode;

@Service
public class JobService {

	public static final String ADMIN_ROLE = "admin";

	private static final int MAX_LIST = 100;

	private final JobRepository repository;

	private final JsonMapper json;

	private final Validator validator;

	private final int maxAttempts;

	public JobService(JobRepository repository, JsonMapper json, Validator validator, ScmProperties properties) {
		this.repository = repository;
		this.json = json;
		this.validator = validator;
		this.maxAttempts = properties.jobs().maxAttempts();
	}

	public record Submission(Job job, boolean created) {
	}

	/** The same idempotency key (per user) returns the original job. */
	public Submission submit(Actor actor, JobType type, String idempotencyKey, JsonNode payload) {
		validate(type, payload);
		String hash = sha256(type.name() + ":" + canonical(payload));
		String key = actor.userId() + ":" + (idempotencyKey == null || idempotencyKey.isBlank()
				? UUID.randomUUID().toString() : idempotencyKey.strip());
		var inserted = repository.insertIfAbsent(type, key, hash, payload, actor.userId(), actor.role(), maxAttempts);
		if (inserted.isPresent()) {
			return new Submission(inserted.get(), true);
		}
		Job existing = repository.findByKey(type, key).orElseThrow();
		if (!existing.requestHash().equals(hash)) {
			throw ApiException.conflict("IDEMPOTENCY_CONFLICT",
					"this idempotency key was already used for a different request");
		}
		return new Submission(existing, false);
	}

	/** Jobs are private to the submitter and admins; others get the same 404 as for a missing job. */
	public Job get(Actor actor, UUID id) {
		return repository.find(id).filter(job -> canView(actor, job))
				.orElseThrow(() -> ApiException.notFound("UNKNOWN_JOB", "no job " + id));
	}

	public List<Job> recent(Actor actor, int limit) {
		return repository.recentBy(actor.userId(), Math.max(1, Math.min(limit, MAX_LIST)));
	}

	private static boolean canView(Actor actor, Job job) {
		return job.submittedBy().equals(actor.userId()) || ADMIN_ROLE.equals(actor.role());
	}

	private void validate(JobType type, JsonNode payload) {
		if (payload == null || !payload.isObject()) {
			throw ApiException.badRequest("VALIDATION_FAILED", "payload must be a JSON object");
		}
		Object typed;
		try {
			typed = json.treeToValue(payload, type.payloadType());
		}
		catch (RuntimeException ex) {
			throw ApiException.badRequest("VALIDATION_FAILED", "payload does not match a " + type + " request");
		}
		Set<ConstraintViolation<Object>> problems = validator.validate(typed);
		if (!problems.isEmpty()) {
			List<FieldViolation> violations = new ArrayList<>();
			for (ConstraintViolation<Object> problem : problems) {
				violations.add(new FieldViolation(problem.getPropertyPath().toString(), problem.getMessage()));
			}
			violations.sort((a, b) -> a.field().compareTo(b.field()));
			throw new RequestValidationException("Request validation failed", violations);
		}
	}

	/** Keys sorted, so equal requests hash equally whatever their key order. */
	private String canonical(JsonNode node) {
		return sorted(node).toString();
	}

	private JsonNode sorted(JsonNode node) {
		if (node.isObject()) {
			Map<String, JsonNode> fields = new TreeMap<>();
			node.properties().forEach(entry -> fields.put(entry.getKey(), sorted(entry.getValue())));
			ObjectNode out = json.createObjectNode();
			fields.forEach(out::set);
			return out;
		}
		if (node.isArray()) {
			var out = json.createArrayNode();
			node.forEach(item -> out.add(sorted(item)));
			return out;
		}
		return node;
	}

	private static String sha256(String text) {
		try {
			return HexFormat.of().formatHex(MessageDigest.getInstance("SHA-256")
					.digest(text.getBytes(StandardCharsets.UTF_8)));
		}
		catch (NoSuchAlgorithmException ex) {
			throw new IllegalStateException(ex);
		}
	}

}
