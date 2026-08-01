package com.scm.platform.security;

import com.scm.platform.error.ApiException;
import org.springframework.core.MethodParameter;
import org.springframework.web.bind.support.WebDataBinderFactory;
import org.springframework.web.context.request.NativeWebRequest;
import org.springframework.web.method.support.HandlerMethodArgumentResolver;
import org.springframework.web.method.support.ModelAndViewContainer;

/**
 * Resolves {@link Actor} controller parameters from the {@code X-User-Id} and {@code X-User-Role}
 * headers. This is the single seam where identity enters the API: token-based authentication
 * replaces this resolver without touching any controller.
 */
public class ActorArgumentResolver implements HandlerMethodArgumentResolver {

	public static final String USER_HEADER = "X-User-Id";

	public static final String ROLE_HEADER = "X-User-Role";

	@Override
	public boolean supportsParameter(MethodParameter parameter) {
		return Actor.class.equals(parameter.getParameterType());
	}

	@Override
	public Object resolveArgument(MethodParameter parameter, ModelAndViewContainer mavContainer,
			NativeWebRequest request, WebDataBinderFactory binderFactory) {
		String user = request.getHeader(USER_HEADER);
		String role = request.getHeader(ROLE_HEADER);
		if (user == null || user.isBlank() || role == null || role.isBlank()) {
			throw ApiException.unauthenticated("missing " + USER_HEADER + " / " + ROLE_HEADER);
		}
		return new Actor(user.strip(), role.strip());
	}

}
