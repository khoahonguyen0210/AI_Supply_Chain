package com.scm.platform.security;

import static org.assertj.core.api.Assertions.assertThat;

import com.scm.platform.support.PostgresContainerConfig;
import java.net.URI;
import java.net.http.HttpClient;
import java.net.http.HttpRequest;
import java.net.http.HttpResponse;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.core.env.Environment;

/**
 * Runs the real servers: the operational port serves metrics, and the API port does not. Tests switch metric
 * export off by default, so it is switched back on here.
 */
@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT,
		properties = { "management.server.port=0", "management.defaults.metrics.export.enabled=true",
				"management.prometheus.metrics.export.enabled=true" })
@Import(PostgresContainerConfig.class)
class ManagementPortTest {

	@Autowired
	private Environment environment;

	private HttpResponse<String> get(String port, String path) throws Exception {
		return HttpClient.newHttpClient().send(
				HttpRequest.newBuilder(URI.create("http://localhost:" + port + path)).GET().build(),
				HttpResponse.BodyHandlers.ofString());
	}

	@Test
	void metricsAndHealthAreServedOnTheManagementPort() throws Exception {
		String management = environment.getProperty("local.management.port");
		assertThat(management).isNotNull().isNotEqualTo(environment.getProperty("local.server.port"));

		HttpResponse<String> health = get(management, "/actuator/health");
		assertThat(health.statusCode()).as(health.body()).isEqualTo(200);
		HttpResponse<String> prometheus = get(management, "/actuator/prometheus");
		assertThat(prometheus.statusCode()).isEqualTo(200);
		assertThat(prometheus.body()).contains("scm_api_request_duration_seconds", "scm_jobs{status=\"queued\"");
	}

	@Test
	void theApiPortNeitherServesActuatorNorAnswersUnauthenticatedApiCalls() throws Exception {
		String api = environment.getProperty("local.server.port");
		assertThat(get(api, "/actuator/prometheus").statusCode()).isNotEqualTo(200);
		assertThat(get(api, "/api/skus").statusCode()).isEqualTo(401);
		assertThat(get(api, "/api/health").statusCode()).isEqualTo(200);
	}

}
