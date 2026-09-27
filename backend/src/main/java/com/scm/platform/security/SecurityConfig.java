package com.scm.platform.security;

import com.nimbusds.jose.jwk.source.ImmutableSecret;
import com.scm.platform.audit.AuditFilter;
import com.scm.platform.audit.AuditService;
import com.scm.platform.error.ApiError;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.time.Clock;
import java.time.Instant;
import java.util.List;
import javax.crypto.SecretKey;
import javax.crypto.spec.SecretKeySpec;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.core.annotation.Order;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.security.config.Customizer;
import org.springframework.security.config.annotation.web.builders.HttpSecurity;
import org.springframework.security.config.annotation.web.configuration.EnableWebSecurity;
import org.springframework.security.config.http.SessionCreationPolicy;
import org.springframework.security.crypto.bcrypt.BCryptPasswordEncoder;
import org.springframework.security.crypto.password.PasswordEncoder;
import org.springframework.security.oauth2.jose.jws.MacAlgorithm;
import org.springframework.security.oauth2.jwt.JwtDecoder;
import org.springframework.security.oauth2.jwt.JwtEncoder;
import org.springframework.security.oauth2.jwt.JwtValidators;
import org.springframework.security.oauth2.jwt.NimbusJwtDecoder;
import org.springframework.security.oauth2.jwt.NimbusJwtEncoder;
import org.springframework.security.oauth2.server.resource.authentication.JwtAuthenticationConverter;
import org.springframework.security.oauth2.server.resource.web.authentication.BearerTokenAuthenticationFilter;
import org.springframework.security.oauth2.server.resource.authentication.JwtGrantedAuthoritiesConverter;
import org.springframework.security.web.AuthenticationEntryPoint;
import org.springframework.security.web.SecurityFilterChain;
import org.springframework.security.web.access.AccessDeniedHandler;
import tools.jackson.databind.json.JsonMapper;

/** Every /api call except health and login needs a valid bearer token; no sessions. */
@Configuration(proxyBeanMethods = false)
@EnableWebSecurity
public class SecurityConfig {

	@Bean
	Clock clock() {
		return Clock.systemUTC();
	}

	@Bean
	RateLimiter rateLimiter(Clock clock) {
		return new RateLimiter(clock);
	}

	@Bean
	PasswordEncoder passwordEncoder() {
		return new BCryptPasswordEncoder();
	}

	@Bean
	SecretKey jwtKey(SecurityProperties properties) {
		return new SecretKeySpec(properties.jwtSecret().getBytes(StandardCharsets.UTF_8), "HmacSHA256");
	}

	@Bean
	JwtEncoder jwtEncoder(SecretKey jwtKey) {
		return new NimbusJwtEncoder(new ImmutableSecret<>(jwtKey));
	}

	@Bean
	JwtDecoder jwtDecoder(SecretKey jwtKey) {
		NimbusJwtDecoder decoder = NimbusJwtDecoder.withSecretKey(jwtKey).macAlgorithm(MacAlgorithm.HS256).build();
		decoder.setJwtValidator(JwtValidators.createDefaultWithIssuer(TokenService.ISSUER));
		return decoder;
	}

	/** Actuator lives on the management port only, so nothing is exposed on the API port. */
	@Bean
	@Order(1)
	SecurityFilterChain managementChain(HttpSecurity http) {
		http.securityMatcher("/actuator/**")
				.authorizeHttpRequests(requests -> requests.anyRequest().permitAll())
				.csrf(csrf -> csrf.disable());
		return http.build();
	}

	@Bean
	@Order(2)
	SecurityFilterChain apiChain(HttpSecurity http, JsonMapper json, AuditService audit, RateLimiter limiter,
			SecurityProperties properties) {
		// Created here, not as beans: as beans they would also run before authentication as servlet filters.
		AuditFilter auditFilter = new AuditFilter(audit, properties.trustForwardedFor());
		RateLimitFilter rateLimitFilter = new RateLimitFilter(limiter, properties, json);
		AuthenticationEntryPoint unauthenticated = (request, response, exception) -> write(json, request, response,
				HttpStatus.UNAUTHORIZED, "UNAUTHENTICATED", "authentication is required or the token is not valid",
				true);
		AccessDeniedHandler forbidden = (request, response, exception) -> write(json, request, response,
				HttpStatus.FORBIDDEN, "FORBIDDEN", "you may not do this", false);
		http.csrf(csrf -> csrf.disable()) // no cookies or sessions: bearer tokens are not sent by the browser on their own
				.sessionManagement(sessions -> sessions.sessionCreationPolicy(SessionCreationPolicy.STATELESS))
				.authorizeHttpRequests(requests -> requests
						.requestMatchers("/api/health", "/api/auth/login").permitAll()
						.requestMatchers("/api/ops/**").hasRole("admin")
						.requestMatchers("/api/**").authenticated()
						.anyRequest().denyAll())
				.oauth2ResourceServer(oauth -> oauth.jwt(jwt -> jwt.jwtAuthenticationConverter(converter()))
						.authenticationEntryPoint(unauthenticated).accessDeniedHandler(forbidden))
				.exceptionHandling(handling -> handling.authenticationEntryPoint(unauthenticated)
						.accessDeniedHandler(forbidden))
				.addFilterAfter(auditFilter, BearerTokenAuthenticationFilter.class)
				.addFilterAfter(rateLimitFilter, AuditFilter.class)
				.headers(Customizer.withDefaults());
		return http.build();
	}

	private static JwtAuthenticationConverter converter() {
		JwtGrantedAuthoritiesConverter authorities = new JwtGrantedAuthoritiesConverter();
		authorities.setAuthoritiesClaimName(TokenService.ROLE_CLAIM);
		authorities.setAuthorityPrefix("ROLE_");
		JwtAuthenticationConverter converter = new JwtAuthenticationConverter();
		converter.setJwtGrantedAuthoritiesConverter(authorities);
		return converter;
	}

	private static void write(JsonMapper json, HttpServletRequest request, HttpServletResponse response,
			HttpStatus status, String code, String message, boolean challenge) throws IOException {
		response.setStatus(status.value());
		response.setContentType(MediaType.APPLICATION_JSON_VALUE);
		if (challenge) {
			response.setHeader(HttpHeaders.WWW_AUTHENTICATE, "Bearer");
		}
		json.writeValue(response.getOutputStream(),
				new ApiError(Instant.now(), status.value(), code, message, request.getRequestURI(), List.of()));
	}

}
