package com.scm.platform.security;

import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.List;
import org.springframework.boot.context.properties.ConfigurationProperties;
import org.springframework.boot.context.properties.bind.DefaultValue;

/** The JWT secret has no default and must be 32+ bytes. */
@ConfigurationProperties(prefix = "scm.security")
public record SecurityProperties(String jwtSecret, @DefaultValue("8h") Duration tokenTtl,
		@DefaultValue List<BootstrapUser> bootstrapUsers, @DefaultValue RateLimits rateLimit,
		@DefaultValue("false") boolean trustForwardedFor, @DefaultValue("true") boolean allowSignUp) {

	public static final int MIN_SECRET_BYTES = 32;

	public static final int MIN_PASSWORD_CHARS = 12;

	/** BCrypt reads only the first 72 bytes, so longer passwords are refused rather than cut. */
	public static final int MAX_PASSWORD_BYTES = 72;

	public static boolean passwordTooLong(String password) {
		return password != null && password.getBytes(StandardCharsets.UTF_8).length > MAX_PASSWORD_BYTES;
	}

	public SecurityProperties {
		if (jwtSecret == null || jwtSecret.getBytes(StandardCharsets.UTF_8).length < MIN_SECRET_BYTES) {
			throw new IllegalStateException("scm.security.jwt-secret must be at least " + MIN_SECRET_BYTES
					+ " bytes; set the SCM_JWT_SECRET environment variable");
		}
		if (tokenTtl.isNegative() || tokenTtl.isZero()) {
			throw new IllegalStateException("scm.security.token-ttl must be positive");
		}
	}

	public static SecurityProperties of(String jwtSecret, Duration tokenTtl, List<BootstrapUser> bootstrapUsers) {
		return new SecurityProperties(jwtSecret, tokenTtl, bootstrapUsers, new RateLimits(10, 5, 300, 30, 5), false,
				true);
	}

	public record RateLimits(@DefaultValue("10") int loginPerIp, @DefaultValue("5") int loginPerUser,
			@DefaultValue("300") int apiPerUser, @DefaultValue("30") int expensivePerUser,
			@DefaultValue("5") int signUpPerIp) {

		public RateLimits {
			if (loginPerIp < 1 || loginPerUser < 1 || apiPerUser < 1 || expensivePerUser < 1 || signUpPerIp < 1) {
				throw new IllegalStateException("rate limits must be at least 1 per minute");
			}
		}

	}

	public record BootstrapUser(String userId, String displayName, String role, String password) {

		public BootstrapUser {
			if (userId == null || userId.isBlank() || role == null || role.isBlank()) {
				throw new IllegalStateException("a bootstrap user needs a user-id and a role");
			}
			if (password == null || password.length() < MIN_PASSWORD_CHARS || passwordTooLong(password)) {
				throw new IllegalStateException("the password of bootstrap user " + userId + " must be at least "
						+ MIN_PASSWORD_CHARS + " characters and at most " + MAX_PASSWORD_BYTES + " bytes");
			}
		}

	}

}
