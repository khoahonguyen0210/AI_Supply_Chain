package com.scm.platform.job;

import com.scm.platform.security.Actor;
import java.time.Instant;
import java.util.UUID;
import tools.jackson.databind.JsonNode;

public record Job(
		UUID id,
		JobType type,
		String idempotencyKey,
		String requestHash,
		JsonNode payload,
		String submittedBy,
		String submittedRole,
		JobStatus status,
		int attempts,
		int maxAttempts,
		Instant runAfter,
		JsonNode result,
		String errorCode,
		String errorMessage,
		String lastError,
		Instant createdAt,
		Instant updatedAt,
		Instant startedAt,
		Instant finishedAt) {

	public Actor actor() {
		return new Actor(submittedBy, submittedRole);
	}

}
