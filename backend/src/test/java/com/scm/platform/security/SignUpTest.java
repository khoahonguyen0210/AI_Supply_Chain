package com.scm.platform.security;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.scm.platform.support.PostgresContainerConfig;
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

@SpringBootTest(properties = "scm.security.rate-limit.sign-up-per-ip=50")
@AutoConfigureMockMvc
@Import(PostgresContainerConfig.class)
class SignUpTest {

	@Autowired
	private MockMvc mockMvc;

	@Autowired
	private JdbcClient jdbc;

	@Autowired
	private JsonMapper json;

	private static MockHttpServletRequestBuilder signUp(String userId, String name, String password) {
		return post("/api/auth/register").contentType(MediaType.APPLICATION_JSON)
				.content("{\"userId\":\"" + userId + "\",\"displayName\":\"" + name + "\",\"password\":\"" + password
						+ "\"}");
	}

	@Test
	void signingUpCreatesAPlannerAndSignsIn() throws Exception {
		String body = mockMvc.perform(signUp("new.planner", "New Planner", "a-long-new-password"))
				.andExpect(status().isCreated())
				.andExpect(jsonPath("$.user.role").value("planner"))
				.andExpect(jsonPath("$.user.displayName").value("New Planner"))
				.andReturn().getResponse().getContentAsString();
		String token = json.readTree(body).path("accessToken").asString();
		mockMvc.perform(get("/api/auth/me").header(HttpHeaders.AUTHORIZATION, "Bearer " + token))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.userId").value("new.planner"));
		mockMvc.perform(post("/api/auth/login").contentType(MediaType.APPLICATION_JSON)
				.content("{\"userId\":\"new.planner\",\"password\":\"a-long-new-password\"}"))
				.andExpect(status().isOk());
		Integer audited = jdbc.sql("SELECT count(*) FROM audit_log WHERE action = 'SIGN_UP' AND outcome = 'SUCCESS'"
				+ " AND actor_user = 'new.planner'").query(Integer.class).single();
		org.assertj.core.api.Assertions.assertThat(audited).isEqualTo(1);
	}

	@Test
	void aRoleCannotBeChosenAtSignUp() throws Exception {
		mockMvc.perform(post("/api/auth/register").contentType(MediaType.APPLICATION_JSON)
				.content("{\"userId\":\"sneaky\",\"displayName\":\"Sneaky\",\"password\":\"a-long-new-password\","
						+ "\"role\":\"admin\"}"))
				.andExpect(status().isCreated())
				.andExpect(jsonPath("$.user.role").value("planner"));
	}

	@Test
	void takenUserIdsAreRefusedIgnoringCase() throws Exception {
		mockMvc.perform(signUp("Pat", "Not Pat", "a-long-new-password"))
				.andExpect(status().isConflict())
				.andExpect(jsonPath("$.code").value("USER_ID_TAKEN"));
		mockMvc.perform(signUp("ROOT", "Not Root", "a-long-new-password")).andExpect(status().isConflict());
	}

	@Test
	void weakPasswordsAndBadUserIdsAreRejected() throws Exception {
		mockMvc.perform(signUp("short.pw", "Short", "too-short")).andExpect(status().isBadRequest());
		mockMvc.perform(signUp("a b", "Spaces", "a-long-new-password")).andExpect(status().isBadRequest());
		mockMvc.perform(signUp("x", "Too short id", "a-long-new-password")).andExpect(status().isBadRequest());
	}

}
