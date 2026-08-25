package com.scm.platform.security;

import com.scm.platform.audit.AuditService;
import com.scm.platform.audit.AuditService.Outcome;
import com.scm.platform.error.ApiException;
import com.scm.platform.security.TokenService.IssuedToken;
import com.scm.platform.security.UserRepository.UserRow;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.time.Instant;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/auth")
public class AuthController {

	private final UserService users;

	private final UserRepository repository;

	private final TokenService tokens;

	private final RateLimiter limiter;

	private final SecurityProperties properties;

	private final AuditService audit;

	public AuthController(UserService users, UserRepository repository, TokenService tokens, RateLimiter limiter,
			SecurityProperties properties, AuditService audit) {
		this.users = users;
		this.repository = repository;
		this.tokens = tokens;
		this.limiter = limiter;
		this.properties = properties;
		this.audit = audit;
	}

	public record LoginRequest(@NotBlank @Size(max = 64) String userId, @NotBlank @Size(max = 200) String password) {
	}

	public record Profile(String userId, String displayName, String role) {
	}

	public record LoginResponse(String accessToken, String tokenType, Instant expiresAt, Profile user) {
	}

	/** The same answer for an unknown user, a wrong password and a deactivated account. */
	@PostMapping("/login")
	public LoginResponse login(@Valid @RequestBody LoginRequest request, HttpServletRequest http) {
		String ip = ClientAddress.of(http, properties.trustForwardedFor());
		throttle(request.userId(), ip);
		UserRow user = users.authenticate(request.userId(), request.password()).orElse(null);
		if (user == null) {
			audit.record(request.userId(), null, "LOGIN", "/api/auth/login", Outcome.DENIED, 401, ip,
					"wrong user id or password, or inactive account");
			throw new ApiException(401, "INVALID_CREDENTIALS", "user id or password is wrong");
		}
		audit.record(user.userId(), user.role(), "LOGIN", "/api/auth/login", Outcome.SUCCESS, 200, ip, null);
		IssuedToken token = tokens.issue(user.userId(), user.role());
		return new LoginResponse(token.value(), "Bearer", token.expiresAt(),
				new Profile(user.userId(), user.displayName(), user.role()));
	}

	/** Limits guesses per client address and per account, so one attacker cannot grind through passwords. */
	private void throttle(String userId, String ip) {
		var perIp = limiter.tryAcquire("login:ip:" + ip, properties.rateLimit().loginPerIp());
		var perUser = limiter.tryAcquire("login:user:" + userId.toLowerCase(), properties.rateLimit().loginPerUser());
		if (!perIp.allowed() || !perUser.allowed()) {
			audit.record(userId, null, "LOGIN", "/api/auth/login", Outcome.LIMITED, 429, ip, "too many attempts");
			throw new RateLimitedException(Math.max(perIp.retryAfterSeconds(), perUser.retryAfterSeconds()));
		}
	}

	@GetMapping("/me")
	public Profile me(Actor actor) {
		UserRow user = repository.find(actor.userId()).filter(UserRow::active)
				.orElseThrow(() -> ApiException.unauthenticated("this account is no longer active"));
		return new Profile(user.userId(), user.displayName(), user.role());
	}

}
