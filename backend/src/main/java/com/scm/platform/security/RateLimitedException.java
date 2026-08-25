package com.scm.platform.security;

public class RateLimitedException extends RuntimeException {

	private final long retryAfterSeconds;

	public RateLimitedException(long retryAfterSeconds) {
		super("too many requests; try again in " + retryAfterSeconds + " seconds");
		this.retryAfterSeconds = retryAfterSeconds;
	}

	public long retryAfterSeconds() {
		return retryAfterSeconds;
	}

}
