package com.scm.platform.forecast;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.content;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.jsonPath;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.method;
import static org.springframework.test.web.client.match.MockRestRequestMatchers.requestTo;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withStatus;
import static org.springframework.test.web.client.response.MockRestResponseCreators.withSuccess;

import com.scm.platform.forecast.ForecastDtos.ForecastRequest;
import com.scm.platform.forecast.ForecastDtos.ForecastResponse;
import com.scm.platform.mlservice.MlServiceException;
import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.time.LocalDate;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.test.web.client.MockRestServiceServer;
import org.springframework.web.client.RestClient;

class PythonForecastClientTest {

	private static final Path CONTRACTS = Path.of("..", "docs", "contracts");

	private MockRestServiceServer server;

	private PythonForecastClient client;

	@BeforeEach
	void setUp() {
		RestClient.Builder builder = RestClient.builder().baseUrl("http://ml.test");
		server = MockRestServiceServer.bindTo(builder).build();
		client = new PythonForecastClient(builder.build());
	}

	private static ForecastRequest request() {
		return new ForecastRequest("SKU-001", "R1", LocalDate.of(2024, 12, 30), 2);
	}

	@Test
	void parsesTheCommittedExampleResponseAndSendsTheV1Request() throws IOException {
		String example = Files.readString(CONTRACTS.resolve("forecast-response-v1.example.json"));
		server.expect(requestTo("http://ml.test/v1/forecast"))
				.andExpect(method(HttpMethod.POST))
				.andExpect(content().contentTypeCompatibleWith(MediaType.APPLICATION_JSON))
				.andExpect(jsonPath("$.schemaVersion").value("1"))
				.andExpect(jsonPath("$.skuId").value("SKU-001"))
				.andExpect(jsonPath("$.regionId").value("R1"))
				.andExpect(jsonPath("$.asOf").value("2024-12-30"))
				.andExpect(jsonPath("$.horizonWeeks").value(2))
				.andRespond(withSuccess(example, MediaType.APPLICATION_JSON));

		ForecastResponse response = client.forecast(request());

		assertThat(response.schemaVersion()).isEqualTo("1");
		assertThat(response.method()).isEqualTo("lightgbm-cqr");
		assertThat(response.intervalLevel()).isEqualTo(0.8);
		assertThat(response.points()).hasSize(2);
		assertThat(response.points().get(0).weekStart()).isEqualTo(LocalDate.of(2024, 12, 30));
		assertThat(response.points().get(0).upper()).isEqualTo(31.0);
		server.verify();
	}

	@Test
	void relaysStructuredErrorsFromTheMlService() {
		server.expect(requestTo("http://ml.test/v1/forecast"))
				.andRespond(withStatus(HttpStatus.NOT_FOUND).contentType(MediaType.APPLICATION_JSON)
						.body("{\"code\":\"UNKNOWN_SERIES\",\"message\":\"no demand history for SKU-001 in R1\"}"));

		assertThatThrownBy(() -> client.forecast(request()))
				.isInstanceOfSatisfying(MlServiceException.class, ex -> {
					assertThat(ex.status()).isEqualTo(404);
					assertThat(ex.code()).isEqualTo("UNKNOWN_SERIES");
				});
	}

	@Test
	void rejectsAnUnexpectedSchemaVersion() {
		server.expect(requestTo("http://ml.test/v1/forecast"))
				.andRespond(withSuccess("{\"schemaVersion\":\"2\",\"points\":[]}", MediaType.APPLICATION_JSON));

		assertThatThrownBy(() -> client.forecast(request()))
				.isInstanceOfSatisfying(MlServiceException.class,
						ex -> assertThat(ex.code()).isEqualTo("ML_CONTRACT_MISMATCH"));
	}

	@Test
	void mapsUnparseableFailuresToBadGateway() {
		server.expect(requestTo("http://ml.test/v1/forecast"))
				.andRespond(withStatus(HttpStatus.INTERNAL_SERVER_ERROR).body("oops"));

		assertThatThrownBy(() -> client.forecast(request()))
				.isInstanceOfSatisfying(MlServiceException.class, ex -> {
					assertThat(ex.status()).isEqualTo(502);
					assertThat(ex.code()).isEqualTo("ML_SERVICE_ERROR");
				});
	}

}
