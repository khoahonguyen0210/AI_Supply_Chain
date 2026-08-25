package com.scm.platform.support;

import com.nimbusds.jose.jwk.source.ImmutableSecret;
import java.nio.charset.StandardCharsets;
import java.time.Instant;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.http.HttpHeaders;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.JwsHeader;
import org.springframework.security.oauth2.jwt.JwtClaimsSet;
import org.springframework.security.oauth2.jwt.JwtEncoderParameters;
import org.springframework.security.oauth2.jwt.NimbusJwtEncoder;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;

public final class TestAuth {

	public static final String SECRET = "test-only-signing-key-0123456789-abcdefghij";

	private static final NimbusJwtEncoder ENCODER = new NimbusJwtEncoder(
			new ImmutableSecret<>(new SecretKeySpec(SECRET.getBytes(StandardCharsets.UTF_8), "HmacSHA256")));

	private TestAuth() {
	}

	public static String token(String userId, String role, Instant issuedAt, Instant expiresAt, String issuer) {
		JwtClaimsSet claims = JwtClaimsSet.builder().issuer(issuer).subject(userId).issuedAt(issuedAt)
				.expiresAt(expiresAt).claim("role", role).build();
		return ENCODER.encode(JwtEncoderParameters.from(JwsHeader.with(MacAlgorithm.HS256).build(), claims))
				.getTokenValue();
	}

	public static String token(String userId, String role) {
		Instant now = Instant.now();
		return token(userId, role, now, now.plusSeconds(3600), "scm-backend");
	}

	public static String bearer(String userId, String role) {
		return "Bearer " + token(userId, role);
	}

	public static MockHttpServletRequestBuilder as(MockHttpServletRequestBuilder request, String userId,
			String role) {
		return request.header(HttpHeaders.AUTHORIZATION, bearer(userId, role));
	}

}
