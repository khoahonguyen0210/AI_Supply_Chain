package com.scm.platform.mlservice;

import java.util.function.Supplier;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClientException;
import org.springframework.web.client.RestClientResponseException;

public final class MlErrors {

	private MlErrors() {
	}

	public static <T> T call(String contract, Supplier<T> call) {
		try {
			return call.get();
		}
		catch (RestClientResponseException ex) {
			throw toServiceException(ex);
		}
		catch (ResourceAccessException ex) {
			throw new MlServiceException(503, "ML_SERVICE_UNAVAILABLE", "ML service is unreachable");
		}
		catch (RestClientException ex) {
			throw contractMismatch(contract);
		}
	}

	public static MlServiceException contractMismatch(String contract) {
		return new MlServiceException(502, "ML_CONTRACT_MISMATCH",
				"ML service returned a response that does not match " + contract);
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
