package com.scm.platform.security;

import com.scm.platform.error.ApiException;
import org.springframework.core.MethodParameter;
import org.springframework.security.core.context.SecurityContextHolder;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationToken;
import org.springframework.web.bind.support.WebDataBinderFactory;
import org.springframework.web.context.request.NativeWebRequest;
import org.springframework.web.method.support.HandlerMethodArgumentResolver;
import org.springframework.web.method.support.ModelAndViewContainer;

/**
 * Resolves {@link Actor} controller parameters from the validated access token of the current request, so
 * controllers never read identity from anything the caller can set freely.
 */
public class ActorArgumentResolver implements HandlerMethodArgumentResolver {

	@Override
	public boolean supportsParameter(MethodParameter parameter) {
		return Actor.class.equals(parameter.getParameterType());
	}

	@Override
	public Object resolveArgument(MethodParameter parameter, ModelAndViewContainer mavContainer,
			NativeWebRequest request, WebDataBinderFactory binderFactory) {
		return current();
	}

	/** The signed-in actor, or a 401 when the request carries no valid token. */
	public static Actor current() {
		if (SecurityContextHolder.getContext().getAuthentication() instanceof JwtAuthenticationToken token) {
			String role = token.getToken().getClaimAsString(TokenService.ROLE_CLAIM);
			String user = token.getToken().getSubject();
			if (user != null && !user.isBlank() && role != null && !role.isBlank()) {
				return new Actor(user, role);
			}
		}
		throw ApiException.unauthenticated("authentication is required");
	}

}
