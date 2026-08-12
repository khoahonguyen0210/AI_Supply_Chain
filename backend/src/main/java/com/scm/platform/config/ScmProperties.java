package com.scm.platform.config;

import java.time.Duration;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/** Application settings bound from the {@code scm.*} configuration namespace. */
@ConfigurationProperties(prefix = "scm")
public record ScmProperties(String serviceName, String version, String mlServiceUrl,
		@DefaultValue("120s") Duration mlReadTimeout, @DefaultValue Jobs jobs) {

	/**
	 * Async job processing.
	 *
	 * @param workerEnabled whether this instance polls the queue and runs jobs
	 * @param pollInterval pause between queue polls when no job is runnable
	 * @param lease how long a worker owns a claimed job before another may take it over
	 * @param maxAttempts runs of one job (first try included) before it is marked failed
	 * @param retryBackoff delay before the first retry; doubled for each further attempt
	 */
	public record Jobs(
			@DefaultValue("true") boolean workerEnabled,
			@DefaultValue("1s") Duration pollInterval,
			@DefaultValue("5m") Duration lease,
			@DefaultValue("3") int maxAttempts,
			@DefaultValue("2s") Duration retryBackoff) {
	}

}
