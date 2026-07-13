package com.scm.platform.forecast;

import com.scm.platform.forecast.ForecastDtos.ForecastRequest;
import com.scm.platform.forecast.ForecastDtos.ForecastResponse;
import com.scm.platform.forecast.ForecastDtos.MlForecastRequest;
import com.scm.platform.mlservice.MlErrorBody;
import com.scm.platform.mlservice.MlServiceException;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;

public class PythonForecastClient implements ForecastClient {

	private final RestClient restClient;

	public PythonForecastClient(RestClient restClient) {
		this.restClient = restClient;
	}

	@Override
	public ForecastResponse forecast(ForecastRequest request) {
		ForecastResponse response;
		try {
			response = restClient.post()
					.uri("/v1/forecast")
					.body(MlForecastRequest.from(request))
					.retrieve()
					.body(ForecastResponse.class);
		}
		catch (RestClientResponseException ex) {
			throw toServiceException(ex);
		}
		catch (ResourceAccessException ex) {
			throw new MlServiceException(503, "ML_SERVICE_UNAVAILABLE", "ML service is unreachable");
		}
		catch (RestClientException ex) {
			throw contractMismatch();
		}
		if (response == null || !ForecastDtos.SCHEMA_VERSION.equals(response.schemaVersion())) {
			throw contractMismatch();
		}
		return response;
	}

	private static MlServiceException contractMismatch() {
		return new MlServiceException(502, "ML_CONTRACT_MISMATCH",
				"ML service returned a response that does not match forecast schema version "
						+ ForecastDtos.SCHEMA_VERSION);
	}

	private static MlServiceException toServiceException(RestClientResponseException ex) {
		MlErrorBody error = null;
		try {
			error = ex.getResponseBodyAs(MlErrorBody.class);
		}
		catch (RuntimeException ignored) {
			// body was not the documented error contract; fall through to the generic error
		}
		if (error != null && error.code() != null) {
			return new MlServiceException(ex.getStatusCode().value(), error.code(), error.message());
		}
		return new MlServiceException(502, "ML_SERVICE_ERROR", "ML service call failed");
	}

}
