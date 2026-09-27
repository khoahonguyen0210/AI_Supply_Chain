package com.scm.platform.security;

import jakarta.servlet.http.HttpServletRequest;

public final class ClientAddress {

	private ClientAddress() {
	}

	/** X-Forwarded-For is used only when trustForwardedFor is enabled. */
	public static String of(HttpServletRequest request, boolean trustForwardedFor) {
		if (trustForwardedFor) {
			String forwarded = request.getHeader("X-Forwarded-For");
			if (forwarded != null && !forwarded.isBlank()) {
				return forwarded.split(",")[0].strip();
			}
		}
		return request.getRemoteAddr();
	}

}
