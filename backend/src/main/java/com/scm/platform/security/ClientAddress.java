package com.scm.platform.security;

import jakarta.servlet.http.HttpServletRequest;

/** The address a request came from, for rate limiting and the audit log. */
public final class ClientAddress {

	private ClientAddress() {
	}

	/**
	 * The peer address, or with {@code trustForwardedFor} the first address a trusted proxy reported. The
	 * forwarded header is only honoured when explicitly enabled, because anyone can send it.
	 */
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
