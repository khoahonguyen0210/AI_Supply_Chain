package com.scm.platform.error;

import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.get;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.scm.platform.support.PostgresContainerConfig;
import com.scm.platform.support.TestAuth;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.web.servlet.MockMvc;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@SpringBootTest
@AutoConfigureMockMvc
@Import({PostgresContainerConfig.class, GlobalExceptionHandlerTest.FailingController.class})
class GlobalExceptionHandlerTest {

	@Autowired
	private MockMvc mockMvc;

	@Test
	void validationFailureReturnsStructuredBadRequest() throws Exception {
		mockMvc.perform(post("/api/test-support/validate").header("Authorization", TestAuth.bearer("pat", "planner"))
						.contentType(MediaType.APPLICATION_JSON)
						.content("{\"name\":\"\"}"))
				.andExpect(status().isBadRequest())
				.andExpect(jsonPath("$.code").value("VALIDATION_FAILED"))
				.andExpect(jsonPath("$.status").value(400))
				.andExpect(jsonPath("$.path").value("/api/test-support/validate"))
				.andExpect(jsonPath("$.violations[0].field").value("name"));
	}

	@Test
	void unknownPathReturnsStructuredNotFound() throws Exception {
		mockMvc.perform(get("/api/does-not-exist").header("Authorization", TestAuth.bearer("pat", "planner")))
				.andExpect(status().isNotFound())
				.andExpect(jsonPath("$.code").value("NOT_FOUND"))
				.andExpect(jsonPath("$.path").value("/api/does-not-exist"));
	}

	@Test
	void unexpectedExceptionReturnsStructuredServerErrorWithoutLeakingDetails() throws Exception {
		mockMvc.perform(get("/api/test-support/boom").header("Authorization", TestAuth.bearer("pat", "planner")))
				.andExpect(status().isInternalServerError())
				.andExpect(jsonPath("$.code").value("INTERNAL_ERROR"))
				.andExpect(jsonPath("$.message").value("Unexpected server error"));
	}

	@RestController
	@RequestMapping("/api/test-support")
	static class FailingController {

		record Payload(@NotBlank String name) {
		}

		@PostMapping("/validate")
		String validate(@Valid @RequestBody Payload payload) {
			return payload.name();
		}

		@GetMapping("/boom")
		String boom() {
			throw new IllegalStateException("secret internal detail");
		}

	}

}
