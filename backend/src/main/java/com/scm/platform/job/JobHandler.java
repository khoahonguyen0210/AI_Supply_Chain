package com.scm.platform.job;

import tools.jackson.databind.JsonNode;

public interface JobHandler {

	JobType type();

	/** An ML 5xx error is retried; anything else fails the job. */
	JsonNode handle(Job job);

}
