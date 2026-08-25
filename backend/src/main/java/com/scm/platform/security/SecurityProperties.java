package com.scm.platform.security;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/**
 * Authentication and abuse-protection settings under {@code scm.security}. The JWT signing secret has no
 * default: the service refuses to start without one that is long enough, so a missing secret can never
 * become a weak one.
 *
 * @param jwtSecret HMAC-SHA256 signing key (at least 32 bytes), from the {@code SCM_JWT_SECRET} environment variable
 * @param tokenTtl how long an access token stays valid
 * @param bootstrapUsers accounts created or refreshed at startup (their passwords come from the environment)
 * @param rateLimit request limits per minute
 * @param trustForwardedFor use the first {@code X-Forwarded-For} address as the client address; only enable behind a
 *        proxy that sets it, otherwise callers could pick their own address
 */
@ConfigurationProperties(prefix = "scm.security")
public record SecurityProperties(String jwtSecret, @DefaultValue("8h") Duration tokenTtl,
		@DefaultValue List<BootstrapUser> bootstrapUsers, @DefaultValue RateLimits rateLimit,
		@DefaultValue("false") boolean trustForwardedFor) {

	public static final int MIN_SECRET_BYTES = 32;

	public static final int MIN_PASSWORD_CHARS = 12;

	public SecurityProperties {
		if (jwtSecret == null || jwtSecret.getBytes(StandardCharsets.UTF_8).length < MIN_SECRET_BYTES) {
			throw new IllegalStateException("scm.security.jwt-secret must be at least " + MIN_SECRET_BYTES
					+ " bytes; set the SCM_JWT_SECRET environment variable");
		}
		if (tokenTtl.isNegative() || tokenTtl.isZero()) {
			throw new IllegalStateException("scm.security.token-ttl must be positive");
		}
	}

	/** Properties with the default rate limits, for code that builds them by hand. */
	public static SecurityProperties of(String jwtSecret, Duration tokenTtl, List<BootstrapUser> bootstrapUsers) {
		return new SecurityProperties(jwtSecret, tokenTtl, bootstrapUsers, new RateLimits(10, 5, 300, 30), false);
	}

	/**
	 * Requests allowed per minute (a burst up to the limit is fine).
	 *
	 * @param loginPerIp login attempts per client address
	 * @param loginPerUser login attempts per user id, however many addresses they come from
	 * @param apiPerUser all API calls per signed-in user
	 * @param expensivePerUser calls that start heavy work (jobs, agent tasks, scenario runs, questions, ranking)
	 */
	public record RateLimits(@DefaultValue("10") int loginPerIp, @DefaultValue("5") int loginPerUser,
			@DefaultValue("300") int apiPerUser, @DefaultValue("30") int expensivePerUser) {

		public RateLimits {
			if (loginPerIp < 1 || loginPerUser < 1 || apiPerUser < 1 || expensivePerUser < 1) {
				throw new IllegalStateException("rate limits must be at least 1 per minute");
			}
		}

	}

	public record BootstrapUser(String userId, String displayName, String role, String password) {

		public BootstrapUser {
			if (userId == null || userId.isBlank() || role == null || role.isBlank()) {
				throw new IllegalStateException("a bootstrap user needs a user-id and a role");
			}
			if (password == null || password.length() < MIN_PASSWORD_CHARS) {
				throw new IllegalStateException("the password of bootstrap user " + userId + " must be at least "
						+ MIN_PASSWORD_CHARS + " characters");
			}
		}

	}

}
