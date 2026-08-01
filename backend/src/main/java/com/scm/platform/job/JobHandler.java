package com.scm.platform.job;

import tools.jackson.databind.JsonNode;

/** Runs one kind of job and returns the durable result. Failures are reported as exceptions. */
public interface JobHandler {

	JobType type();

	/**
	 * Executes the job. A {@link com.scm.platform.mlservice.MlServiceException} with a 5xx status is
	 * retried by the worker; any other exception fails the job permanently.
	 */
	JsonNode handle(Job job);

}
