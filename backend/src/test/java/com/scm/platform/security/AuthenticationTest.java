package com.scm.platform.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.scm.platform.support.PostgresContainerConfig;
import com.scm.platform.support.TestAuth;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.time.Instant;
import java.util.Base64;
import java.util.List;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.HttpHeaders;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import tools.jackson.databind.json.JsonMapper;

@SpringBootTest
@AutoConfigureMockMvc
@Import(PostgresContainerConfig.class)
class AuthenticationTest {

	@Autowired
	private MockMvc mockMvc;

	@Autowired
	private JdbcClient jdbc;

	@Autowired
	private JsonMapper json;

	@AfterEach
	void reactivate() {
		jdbc.sql("UPDATE app_user SET active = true").update();
	}

	private static MockHttpServletRequestBuilder login(String userId, String password) {
		return post("/api/auth/login").contentType(MediaType.APPLICATION_JSON)
				.content("{\"userId\":\"" + userId + "\",\"password\":\"" + password + "\"}");
	}

	private String loginToken(String userId, String password) throws Exception {
		String body = mockMvc.perform(login(userId, password)).andExpect(status().isOk()).andReturn().getResponse()
				.getContentAsString();
		return json.readTree(body).path("accessToken").asString();
	}

	private static MockHttpServletRequestBuilder withToken(MockHttpServletRequestBuilder request, String token) {
		return request.header(HttpHeaders.AUTHORIZATION, "Bearer " + token);
	}

	@Test
	void signingInGivesATokenThatOpensTheApi() throws Exception {
		mockMvc.perform(login("pat", "pat-test-password-1"))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.tokenType").value("Bearer"))
				.andExpect(jsonPath("$.user.role").value("planner"))
				.andExpect(jsonPath("$.user.displayName").value("Pat"))
				.andExpect(jsonPath("$.expiresAt").isNotEmpty());

		String token = loginToken("pat", "pat-test-password-1");
		mockMvc.perform(withToken(get("/api/auth/me"), token))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.userId").value("pat"))
				.andExpect(jsonPath("$.role").value("planner"));
		mockMvc.perform(withToken(get("/api/skus"), token)).andExpect(status().isOk());
	}

	@Test
	void everyWayOfGettingCredentialsWrongLooksTheSame() throws Exception {
		String wrongPassword = mockMvc.perform(login("pat", "not-the-password")).andExpect(status().isUnauthorized())
				.andReturn().getResponse().getContentAsString();
		String unknownUser = mockMvc.perform(login("nobody", "not-the-password")).andExpect(status().isUnauthorized())
				.andReturn().getResponse().getContentAsString();
		jdbc.sql("UPDATE app_user SET active = false WHERE user_id = 'pat'").update();
		String deactivated = mockMvc.perform(login("pat", "pat-test-password-1"))
				.andExpect(status().isUnauthorized()).andReturn().getResponse().getContentAsString();

		for (String body : List.of(wrongPassword, unknownUser, deactivated)) {
			assertThat(json.readTree(body).path("code").asString()).isEqualTo("INVALID_CREDENTIALS");
			assertThat(json.readTree(body).path("message").asString()).isEqualTo("user id or password is wrong");
		}
	}

	@Test
	void loginRequiresBothFields() throws Exception {
		mockMvc.perform(post("/api/auth/login").contentType(MediaType.APPLICATION_JSON).content("{\"userId\":\"\"}"))
				.andExpect(status().isBadRequest()).andExpect(jsonPath("$.code").value("VALIDATION_FAILED"));
	}

	@Test
	void passwordsAreStoredOnlyAsHashes() {
		String hash = jdbc.sql("SELECT password_hash FROM app_user WHERE user_id = 'pat'").query(String.class)
				.single();
		assertThat(hash).startsWith("$2").doesNotContain("pat-test-password-1");
	}

	@Test
	void requestsWithoutATokenAreRejectedWithAChallenge() throws Exception {
		mockMvc.perform(get("/api/skus"))
				.andExpect(status().isUnauthorized())
				.andExpect(header().string(HttpHeaders.WWW_AUTHENTICATE, "Bearer"))
				.andExpect(jsonPath("$.code").value("UNAUTHENTICATED"))
				.andExpect(jsonPath("$.path").value("/api/skus"));
		mockMvc.perform(get("/api/health")).andExpect(status().isOk());
	}

	@Test
	void identityHeadersAloneNoLongerSignAnyoneIn() throws Exception {
		mockMvc.perform(get("/api/skus").header("X-User-Id", "root").header("X-User-Role", "admin"))
				.andExpect(status().isUnauthorized());
	}

	@Test
	void forgedExpiredAndForeignTokensAreRejected() throws Exception {
		Instant now = Instant.now();
		String expired = TestAuth.token("pat", "planner", now.minusSeconds(7200), now.minusSeconds(3600),
				"scm-backend");
		String wrongIssuer = TestAuth.token("pat", "planner", now, now.plusSeconds(3600), "someone-else");
		String valid = TestAuth.token("pat", "planner");
		String[] parts = valid.split("\\.");
		String elevated = Base64.getUrlEncoder().withoutPadding()
				.encodeToString("{\"iss\":\"scm-backend\",\"sub\":\"pat\",\"role\":\"admin\",\"exp\":9999999999}"
						.getBytes(StandardCharsets.UTF_8));
		String tampered = parts[0] + "." + elevated + "." + parts[2];
		String unsigned = Base64.getUrlEncoder().withoutPadding()
				.encodeToString("{\"alg\":\"none\"}".getBytes(StandardCharsets.UTF_8)) + "." + elevated + ".";

		for (String bad : List.of(expired, wrongIssuer, tampered, unsigned, "not-a-jwt")) {
			mockMvc.perform(withToken(get("/api/skus"), bad)).andExpect(status().isUnauthorized())
					.andExpect(jsonPath("$.code").value("UNAUTHENTICATED"));
		}
	}

	@Test
	void aTokenWithoutARoleIsNotAnIdentity() throws Exception {
		Instant now = Instant.now();
		String noRole = TestAuth.token("pat", "", now, now.plusSeconds(3600), "scm-backend");
		mockMvc.perform(withToken(get("/api/skus"), noRole)).andExpect(status().isUnauthorized());
	}

	@Test
	void roleBasedRulesApplyToTheTokenRole() throws Exception {
		mockMvc.perform(withToken(get("/api/ops/summary"), loginToken("pat", "pat-test-password-1")))
				.andExpect(status().isForbidden()).andExpect(jsonPath("$.code").value("FORBIDDEN"));
		mockMvc.perform(withToken(get("/api/ops/summary"), loginToken("root", "root-test-password-1")))
				.andExpect(status().isOk());
	}

	@Test
	void aDeactivatedAccountLosesAccessEvenWithAnUnexpiredToken() throws Exception {
		String token = loginToken("pat", "pat-test-password-1");
		jdbc.sql("UPDATE app_user SET active = false WHERE user_id = 'pat'").update();
		mockMvc.perform(withToken(get("/api/auth/me"), token)).andExpect(status().isUnauthorized());
	}

	@Test
	void theServiceRefusesToStartWithAMissingOrShortSigningSecret() {
		assertThatThrownBy(() -> SecurityProperties.of(null, Duration.ofHours(1), List.of()))
				.isInstanceOf(IllegalStateException.class).hasMessageContaining("SCM_JWT_SECRET");
		assertThatThrownBy(() -> SecurityProperties.of("too-short", Duration.ofHours(1), List.of()))
				.isInstanceOf(IllegalStateException.class);
		assertThatThrownBy(() -> SecurityProperties.of("x".repeat(40), Duration.ZERO, List.of()))
				.isInstanceOf(IllegalStateException.class);
		SecurityProperties.of("x".repeat(32), Duration.ofHours(1), List.of());
	}

	@Test
	void bootstrapAccountsNeedRealPasswords() {
		assertThatThrownBy(() -> new SecurityProperties.BootstrapUser("u", "U", "planner", "short"))
				.isInstanceOf(IllegalStateException.class).hasMessageContaining("at least");
		assertThatThrownBy(() -> new SecurityProperties.BootstrapUser("", "U", "planner", "long-enough-password"))
				.isInstanceOf(IllegalStateException.class);
	}

}
