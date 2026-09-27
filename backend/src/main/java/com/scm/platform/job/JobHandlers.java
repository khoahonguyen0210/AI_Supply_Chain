package com.scm.platform.job;

import com.scm.platform.forecast.ForecastClient;
import com.scm.platform.forecast.ForecastDtos.ForecastRequest;
import com.scm.platform.mlservice.MlEngineClient;
import com.scm.platform.mlservice.MlServiceException;
import java.util.List;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;
import tools.jackson.databind.node.ArrayNode;
import tools.jackson.databind.node.ObjectNode;

@Configuration(proxyBeanMethods = false)
public class JobHandlers {

	@Bean
	JobHandler forecastJobHandler(ForecastClient forecasts, JsonMapper json) {
		return handler(JobType.FORECAST, job -> json.valueToTree(
				forecasts.forecast(json.treeToValue(job.payload(), ForecastRequest.class))));
	}

	@Bean
	JobHandler optimizationJobHandler(MlEngineClient engine) {
		return handler(JobType.OPTIMIZATION, job -> engine.optimize(job.actor(), job.payload()));
	}

	@Bean
	JobHandler scenarioJobHandler(MlEngineClient engine) {
		return handler(JobType.SCENARIO, job -> engine.runScenario(job.actor(), job.payload()));
	}

	@Bean
	JobHandler batchEvaluationJobHandler(MlEngineClient engine, JsonMapper json) {
		return handler(JobType.BATCH_EVALUATION, job -> {
			List<String> tasks = json.treeToValue(job.payload(), JobType.BatchEvaluationPayload.class).tasks();
			ArrayNode items = json.createArrayNode();
			int completed = 0;
			for (String text : tasks) {
				ObjectNode item = items.addObject();
				item.put("text", text);
				try {
					JsonNode run = engine.runAgentTask(job.actor(), text);
					item.put("taskId", run.path("taskId").asString(""));
					item.put("status", run.path("status").asString(""));
					item.set("violations", run.path("violations"));
					if (!"FAILED".equals(run.path("status").asString(""))) {
						completed++;
					}
				}
				catch (MlServiceException ex) {
					item.put("status", "ERROR");
					item.put("errorCode", ex.code());
				}
			}
			ObjectNode result = json.createObjectNode();
			result.put("total", tasks.size());
			result.put("handled", completed);
			result.set("items", items);
			return result;
		});
	}

	private static JobHandler handler(JobType type, java.util.function.Function<Job, JsonNode> body) {
		return new JobHandler() {
			@Override
			public JobType type() {
				return type;
			}

			@Override
			public JsonNode handle(Job job) {
				return body.apply(job);
			}
		};
	}

}
