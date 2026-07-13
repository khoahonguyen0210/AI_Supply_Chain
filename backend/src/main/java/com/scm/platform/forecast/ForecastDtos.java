package com.scm.platform.forecast;

import jakarta.validation.constraints.Max;
import jakarta.validation.constraints.Min;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotNull;
import java.time.LocalDate;
import java.util.List;

public final class ForecastDtos {

	public static final String SCHEMA_VERSION = "1";

	private ForecastDtos() {
	}

	public record ForecastRequest(
			@NotBlank String skuId,
			@NotBlank String regionId,
			@NotNull LocalDate asOf,
			@Min(1) @Max(8) Integer horizonWeeks) {

		public int horizonOrDefault() {
			return horizonWeeks == null ? 8 : horizonWeeks;
		}
	}

	public record MlForecastRequest(String schemaVersion, String skuId, String regionId, LocalDate asOf,
			int horizonWeeks) {

		public static MlForecastRequest from(ForecastRequest request) {
			return new MlForecastRequest(SCHEMA_VERSION, request.skuId(), request.regionId(), request.asOf(),
					request.horizonOrDefault());
		}
	}

	public record ForecastPoint(LocalDate weekStart, int horizon, double point, double lower, double upper) {
	}

	public record ForecastResponse(
			String schemaVersion,
			String modelVersion,
			String datasetId,
			String skuId,
			String regionId,
			LocalDate asOf,
			double intervalLevel,
			String method,
			List<ForecastPoint> points) {
	}

}
