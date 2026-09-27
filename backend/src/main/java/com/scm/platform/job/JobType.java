package com.scm.platform.job;

import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.NotEmpty;
import jakarta.validation.constraints.NotNull;
import java.time.LocalDate;
import java.util.List;
import tools.jackson.databind.JsonNode;

public enum JobType {

	FORECAST(ForecastPayload.class),
	OPTIMIZATION(OptimizationPayload.class),
	SCENARIO(ScenarioPayload.class),
	BATCH_EVALUATION(BatchEvaluationPayload.class);

	private final Class<?> payloadType;

	JobType(Class<?> payloadType) {
		this.payloadType = payloadType;
	}

	public Class<?> payloadType() {
		return payloadType;
	}

	public record ForecastPayload(@NotBlank String skuId, @NotBlank String regionId, @NotNull LocalDate asOf,
			Integer horizonWeeks) {
	}

	public record OptimizationPayload(@NotEmpty List<String> skuIds) {
	}

	public record ScenarioPayload(@NotNull JsonNode plan, @NotBlank String scenarioType) {
	}

	public record BatchEvaluationPayload(@NotEmpty List<@NotBlank String> tasks) {
	}

}
