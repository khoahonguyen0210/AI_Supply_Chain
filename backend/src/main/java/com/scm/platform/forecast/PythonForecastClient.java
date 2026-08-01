package com.scm.platform.forecast;

import com.scm.platform.forecast.ForecastDtos.ForecastRequest;
import com.scm.platform.forecast.ForecastDtos.ForecastResponse;
import com.scm.platform.forecast.ForecastDtos.MlForecastRequest;
import com.scm.platform.mlservice.MlErrors;
import org.springframework.web.client.RestClient;

public class PythonForecastClient implements ForecastClient {

	private static final String CONTRACT = "forecast schema version " + ForecastDtos.SCHEMA_VERSION;

	private final RestClient restClient;

	public PythonForecastClient(RestClient restClient) {
		this.restClient = restClient;
	}

	@Override
	public ForecastResponse forecast(ForecastRequest request) {
		ForecastResponse response = MlErrors.call(CONTRACT, () -> restClient.post()
				.uri("/v1/forecast")
				.body(MlForecastRequest.from(request))
				.retrieve()
				.body(ForecastResponse.class));
		if (response == null || !ForecastDtos.SCHEMA_VERSION.equals(response.schemaVersion())) {
			throw MlErrors.contractMismatch(CONTRACT);
		}
		return response;
	}

}
