package com.scm.platform.audit;

import com.scm.platform.audit.AuditService.Outcome;
import com.scm.platform.security.ClientAddress;
import com.scm.platform.security.TokenService;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.util.Set;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.web.filter.OncePerRequestFilter;
import org.springframework.web.servlet.HandlerMapping;

/**
 * Records every change a caller makes and every request that was refused (not signed in, not allowed, rate
 * limited). Reads that succeed are not recorded. It runs inside the security chain, after the token is read,
 * so it knows who is acting; it is created by the security configuration and is not a servlet-level filter.
 * Logins are recorded by the login endpoint itself, which knows the user id that was tried.
 */
public class AuditFilter extends OncePerRequestFilter {

	private static final Set<String> READS = Set.of("GET", "HEAD", "OPTIONS");

	private final AuditService audit;

	private final boolean trustForwardedFor;

	public AuditFilter(AuditService audit, boolean trustForwardedFor) {
		this.audit = audit;
		this.trustForwardedFor = trustForwardedFor;
	}

	@Override
	protected boolean shouldNotFilter(HttpServletRequest request) {
		String path = request.getRequestURI();
		return !path.startsWith("/api/") || path.equals("/api/auth/login") || path.equals("/api/health");
	}

	@Override
	protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
			throws ServletException, IOException {
		try {
			chain.doFilter(request, response);
		}
		finally {
			int status = response.getStatus();
			boolean refused = status == 401 || status == 403 || status == 429;
			if (refused || !READS.contains(request.getMethod())) {
				String user = null;
				String role = null;
				if (SecurityContextHolder.getContext().getAuthentication() instanceof JwtAuthenticationToken token) {
					user = token.getToken().getSubject();
					role = token.getToken().getClaimAsString(TokenService.ROLE_CLAIM);
				}
				Object pattern = request.getAttribute(HandlerMapping.BEST_MATCHING_PATTERN_ATTRIBUTE);
				audit.record(user, role, request.getMethod() + " " + (pattern != null ? pattern : request.getRequestURI()),
						request.getRequestURI(), outcome(status), status,
						ClientAddress.of(request, trustForwardedFor), null);
			}
		}
	}

	private static Outcome outcome(int status) {
		if (status == 401 || status == 403) {
			return Outcome.DENIED;
		}
		if (status == 429) {
			return Outcome.LIMITED;
		}
		return status >= 400 ? Outcome.FAILED : Outcome.SUCCESS;
	}

}
