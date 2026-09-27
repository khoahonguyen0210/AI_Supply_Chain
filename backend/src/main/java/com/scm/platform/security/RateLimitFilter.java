package com.scm.platform.security;

import com.scm.platform.error.ApiError;
import com.scm.platform.security.RateLimiter.Decision;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.time.Instant;
import java.util.List;
import java.util.Set;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.web.filter.OncePerRequestFilter;
import tools.jackson.databind.json.JsonMapper;

/** Per-user rate limit for all calls, plus a tighter one for heavy work. */
public class RateLimitFilter extends OncePerRequestFilter {

	private static final Set<String> HEAVY_POST_PATHS = Set.of("/api/jobs", "/api/agent/tasks",
			"/api/documents/ask", "/api/suppliers/search", "/api/forecasts");

	private final RateLimiter limiter;

	private final SecurityProperties properties;

	private final JsonMapper json;

	public RateLimitFilter(RateLimiter limiter, SecurityProperties properties, JsonMapper json) {
		this.limiter = limiter;
		this.properties = properties;
		this.json = json;
	}

	@Override
	protected boolean shouldNotFilter(HttpServletRequest request) {
		String path = request.getRequestURI();
		return !path.startsWith("/api/") || path.equals("/api/health") || path.equals("/api/auth/login");
	}

	@Override
	protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
			throws ServletException, IOException {
		String who = SecurityContextHolder.getContext().getAuthentication() instanceof JwtAuthenticationToken token
				? "user:" + token.getToken().getSubject()
				: "ip:" + ClientAddress.of(request, properties.trustForwardedFor());
		Decision decision = limiter.tryAcquire("api:" + who, properties.rateLimit().apiPerUser());
		if (decision.allowed() && isHeavy(request)) {
			decision = limiter.tryAcquire("heavy:" + who, properties.rateLimit().expensivePerUser());
		}
		if (!decision.allowed()) {
			response.setStatus(HttpStatus.TOO_MANY_REQUESTS.value());
			response.setHeader(HttpHeaders.RETRY_AFTER, Long.toString(decision.retryAfterSeconds()));
			response.setContentType(MediaType.APPLICATION_JSON_VALUE);
			json.writeValue(response.getOutputStream(), new ApiError(Instant.now(), 429, "RATE_LIMITED",
					"too many requests; try again in " + decision.retryAfterSeconds() + " seconds",
					request.getRequestURI(), List.of()));
			return;
		}
		chain.doFilter(request, response);
	}

	private static boolean isHeavy(HttpServletRequest request) {
		if (!"POST".equals(request.getMethod())) {
			return false;
		}
		String path = request.getRequestURI();
		return HEAVY_POST_PATHS.contains(path) || (path.startsWith("/api/scenarios/") && path.endsWith("/runs"));
	}

}
