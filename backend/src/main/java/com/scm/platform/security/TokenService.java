package com.scm.platform.security;

import java.time.Clock;
import java.time.Instant;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.JwsHeader;
import org.springframework.security.oauth2.jwt.JwtClaimsSet;
import org.springframework.security.oauth2.jwt.JwtEncoder;
import org.springframework.security.oauth2.jwt.JwtEncoderParameters;
import org.springframework.stereotype.Service;

/** The role travels in the signed token; nothing else is trusted. */
@Service
public class TokenService {

	public static final String ROLE_CLAIM = "role";

	public static final String ISSUER = "scm-backend";

	public record IssuedToken(String value, Instant expiresAt) {
	}

	private final JwtEncoder encoder;

	private final SecurityProperties properties;

	private final Clock clock;

	public TokenService(JwtEncoder encoder, SecurityProperties properties, Clock clock) {
		this.encoder = encoder;
		this.properties = properties;
		this.clock = clock;
	}

	public IssuedToken issue(String userId, String role) {
		Instant now = clock.instant();
		Instant expires = now.plus(properties.tokenTtl());
		JwtClaimsSet claims = JwtClaimsSet.builder().issuer(ISSUER).subject(userId).issuedAt(now).expiresAt(expires)
				.claim(ROLE_CLAIM, role).build();
		JwsHeader header = JwsHeader.with(MacAlgorithm.HS256).build();
		return new IssuedToken(encoder.encode(JwtEncoderParameters.from(header, claims)).getTokenValue(), expires);
	}

}
