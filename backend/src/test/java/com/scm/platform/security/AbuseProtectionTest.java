package com.scm.platform.security;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.header;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.scm.platform.mlservice.MlEngineClient;
import com.scm.platform.support.PostgresContainerConfig;
import com.scm.platform.support.TestAuth;
import java.util.List;
import java.util.Map;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.dao.DataAccessException;
import org.springframework.http.MediaType;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.test.web.servlet.request.MockHttpServletRequestBuilder;
import tools.jackson.databind.json.JsonMapper;

@SpringBootTest(properties = { "scm.security.rate-limit.login-per-ip=6", "scm.security.rate-limit.login-per-user=3",
		"scm.security.rate-limit.api-per-user=8", "scm.security.rate-limit.expensive-per-user=2" })
@AutoConfigureMockMvc
@Import(PostgresContainerConfig.class)
class AbuseProtectionTest {

	@Autowired
	private MockMvc mockMvc;

	@Autowired
	private JdbcClient jdbc;

	@Autowired
	private JsonMapper json;

	@MockitoBean
	private MlEngineClient engine;

	private static MockHttpServletRequestBuilder login(String ip, String userId, String password) {
		return post("/api/auth/login").with(request -> {
			request.setRemoteAddr(ip);
			return request;
		}).contentType(MediaType.APPLICATION_JSON)
				.content("{\"userId\":\"" + userId + "\",\"password\":\"" + password + "\"}");
	}

	private List<Map<String, Object>> auditFor(String user) {
		return jdbc.sql("SELECT action, outcome, status, actor_role, client_ip FROM audit_log WHERE actor_user = :u"
				+ " ORDER BY audit_id").param("u", user).query().listOfRows();
	}


	@Test
	void guessingAnAccountPasswordIsStoppedEvenWhenTheNextGuessIsRight() throws Exception {
		for (int i = 0; i < 3; i++) {
			mockMvc.perform(login("10.1.0.1", "pat", "wrong-guess-" + i)).andExpect(status().isUnauthorized());
		}
		mockMvc.perform(login("10.1.0.1", "pat", "pat-test-password-1"))
				.andExpect(status().isTooManyRequests())
				.andExpect(header().exists("Retry-After"))
				.andExpect(jsonPath("$.code").value("RATE_LIMITED"));
	}

	@Test
	void oneAccountBeingLockedOutDoesNotLockOutOthers() throws Exception {
		for (int i = 0; i < 4; i++) {
			mockMvc.perform(login("10.1.0.2", "victim", "wrong-guess-" + i));
		}
		mockMvc.perform(login("10.1.0.3", "root", "root-test-password-1")).andExpect(status().isOk());
	}

	@Test
	void changingTheForwardedForHeaderDoesNotEvadeTheAddressLimit() throws Exception {
		int tooMany = 0;
		for (int i = 0; i < 9; i++) {
			var result = mockMvc.perform(login("10.1.0.4", "spray-" + i, "wrong-guess")
					.header("X-Forwarded-For", "10.0.0." + i)).andReturn();
			if (result.getResponse().getStatus() == 429) {
				tooMany++;
			}
		}
		assertThat(tooMany).isGreaterThanOrEqualTo(3); // limit is 6 per address; the header is not trusted
	}

	@Test
	void everyApiCallCountsAgainstTheUsersLimit() throws Exception {
		String token = TestAuth.bearer("busy", "planner");
		for (int i = 0; i < 8; i++) {
			mockMvc.perform(get("/api/skus").header("Authorization", token)).andExpect(status().isOk());
		}
		mockMvc.perform(get("/api/skus").header("Authorization", token))
				.andExpect(status().isTooManyRequests())
				.andExpect(header().exists("Retry-After"))
				.andExpect(jsonPath("$.code").value("RATE_LIMITED"))
				.andExpect(jsonPath("$.path").value("/api/skus"));
		mockMvc.perform(get("/api/skus").header("Authorization", TestAuth.bearer("calm", "planner")))
				.andExpect(status().isOk());
	}

	@Test
	void callsThatStartHeavyWorkHaveATighterLimit() throws Exception {
		when(engine.askDocuments(any(), any())).thenReturn(json.readTree("{\"status\":\"ANSWERED\"}"));
		String token = TestAuth.bearer("asker", "planner");
		for (int i = 0; i < 2; i++) {
			mockMvc.perform(post("/api/documents/ask").header("Authorization", token)
							.contentType(MediaType.APPLICATION_JSON).content("{\"question\":\"What is the policy?\"}"))
					.andExpect(status().isOk());
		}
		mockMvc.perform(post("/api/documents/ask").header("Authorization", token)
						.contentType(MediaType.APPLICATION_JSON).content("{\"question\":\"What is the policy?\"}"))
				.andExpect(status().isTooManyRequests());
		mockMvc.perform(get("/api/skus").header("Authorization", token)).andExpect(status().isOk());
	}

	@Test
	void healthChecksAreNeverLimited() throws Exception {
		for (int i = 0; i < 20; i++) {
			mockMvc.perform(get("/api/health")).andExpect(status().isOk());
		}
	}


	@Test
	void changesAreAuditedWithWhoDidThemAndHowTheyEnded() throws Exception {
		mockMvc.perform(post("/api/scenarios").header("Authorization", TestAuth.bearer("auditee", "planner"))
						.contentType(MediaType.APPLICATION_JSON)
						.content("{\"name\":\"x\",\"scenarioType\":\"DEMAND_SHOCK\",\"parameters\":{\"factor\":1.2}}"))
				.andExpect(status().isCreated());
		mockMvc.perform(get("/api/scenarios").header("Authorization", TestAuth.bearer("auditee", "planner")))
				.andExpect(status().isOk());

		List<Map<String, Object>> entries = auditFor("auditee");
		assertThat(entries).hasSize(1); // the successful read is not recorded
		assertThat(entries.get(0)).containsEntry("action", "POST /api/scenarios").containsEntry("outcome", "SUCCESS")
				.containsEntry("status", 201).containsEntry("actor_role", "planner");
		assertThat(entries.get(0).get("client_ip")).isNotNull();
	}

	@Test
	void refusedRequestsAreAuditedWhetherOrNotAnyoneWasSignedIn() throws Exception {
		mockMvc.perform(get("/api/ops/summary").header("Authorization", TestAuth.bearer("snoop", "planner")))
				.andExpect(status().isForbidden());
		long before = jdbc.sql("SELECT count(*) FROM audit_log WHERE actor_user IS NULL AND status = 401")
				.query(Long.class).single();
		mockMvc.perform(get("/api/skus")).andExpect(status().isUnauthorized());

		assertThat(auditFor("snoop")).singleElement().satisfies(entry -> {
			assertThat(entry).containsEntry("outcome", "DENIED").containsEntry("status", 403);
			assertThat(entry.get("action")).isEqualTo("GET /api/ops/summary");
		});
		assertThat(jdbc.sql("SELECT count(*) FROM audit_log WHERE actor_user IS NULL AND status = 401")
				.query(Long.class).single()).isEqualTo(before + 1);
	}

	@Test
	void loginsAreAuditedWithoutRecordingPasswords() throws Exception {
		mockMvc.perform(login("10.1.0.5", "root", "wrong-for-audit")).andExpect(status().isUnauthorized());
		mockMvc.perform(login("10.1.0.5", "root", "root-test-password-1")).andExpect(status().isOk());

		List<Map<String, Object>> entries = auditFor("root");
		assertThat(entries).extracting(e -> e.get("action") + " " + e.get("outcome"))
				.contains("LOGIN DENIED", "LOGIN SUCCESS");
		assertThat(jdbc.sql("SELECT count(*) FROM audit_log WHERE detail ILIKE '%password%' AND detail ILIKE '%wrong-for-audit%'")
				.query(Long.class).single()).isZero();
	}

	@Test
	void rateLimitedCallsAreAuditedAsLimited() throws Exception {
		String token = TestAuth.bearer("flooder", "planner");
		for (int i = 0; i < 9; i++) {
			mockMvc.perform(get("/api/skus").header("Authorization", token));
		}
		assertThat(auditFor("flooder")).singleElement()
				.satisfies(entry -> assertThat(entry).containsEntry("outcome", "LIMITED").containsEntry("status", 429));
	}

	@Test
	void theAuditTrailCannotBeAlteredOrErased() {
		jdbc.sql("INSERT INTO audit_log (action, outcome) VALUES ('TEST', 'SUCCESS')").update();
		assertThatThrownBy(() -> jdbc.sql("UPDATE audit_log SET outcome = 'FAILED'").update())
				.isInstanceOf(DataAccessException.class).hasMessageContaining("append-only");
		assertThatThrownBy(() -> jdbc.sql("DELETE FROM audit_log").update()).isInstanceOf(DataAccessException.class);
	}

	@Test
	void adminsCanReadTheAuditTrailAndOthersCannot() throws Exception {
		mockMvc.perform(post("/api/scenarios").header("Authorization", TestAuth.bearer("reader-target", "planner"))
				.contentType(MediaType.APPLICATION_JSON)
				.content("{\"name\":\"y\",\"scenarioType\":\"PRICE_SHOCK\",\"parameters\":{\"factor\":1.1}}"));

		mockMvc.perform(get("/api/ops/audit").param("user", "reader-target").param("outcome", "SUCCESS")
						.header("Authorization", TestAuth.bearer("root", "admin")))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$[0].actorUser").value("reader-target"))
				.andExpect(jsonPath("$[0].action").value("POST /api/scenarios"))
				.andExpect(jsonPath("$[0].outcome").value("SUCCESS"));
		mockMvc.perform(get("/api/ops/audit").header("Authorization", TestAuth.bearer("someone", "finance")))
				.andExpect(status().isForbidden());
	}

}
