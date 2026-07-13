package com.scm.platform.forecast;

import static org.mockito.ArgumentMatchers.any;
import static org.mockito.Mockito.when;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.post;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.jsonPath;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.status;

import com.scm.platform.forecast.ForecastDtos.ForecastPoint;
import com.scm.platform.forecast.ForecastDtos.ForecastResponse;
import com.scm.platform.mlservice.MlServiceException;
import com.scm.platform.support.PostgresContainerConfig;
import java.time.LocalDate;
import java.util.List;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.boot.webmvc.test.autoconfigure.AutoConfigureMockMvc;
import org.springframework.context.annotation.Import;
import org.springframework.http.MediaType;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.springframework.test.web.servlet.MockMvc;

@SpringBootTest
@AutoConfigureMockMvc
@Import(PostgresContainerConfig.class)
class ForecastControllerTest {

	private static final String BODY = "{\"skuId\":\"SKU-001\",\"regionId\":\"R1\","
			+ "\"asOf\":\"2024-12-30\",\"horizonWeeks\":2}";

	@Autowired
	private MockMvc mockMvc;

	@MockitoBean
	private ForecastClient forecastClient;

	@Test
	void returnsTheForecastFromTheClient() throws Exception {
		when(forecastClient.forecast(any())).thenReturn(new ForecastResponse("1", "lgbm-1", "ds-1", "SKU-001",
				"R1", LocalDate.of(2024, 12, 30), 0.8, "lightgbm-cqr",
				List.of(new ForecastPoint(LocalDate.of(2024, 12, 30), 1, 12.5, 0.0, 31.0))));

		mockMvc.perform(post("/api/forecasts").contentType(MediaType.APPLICATION_JSON).content(BODY))
				.andExpect(status().isOk())
				.andExpect(jsonPath("$.modelVersion").value("lgbm-1"))
				.andExpect(jsonPath("$.points[0].upper").value(31.0))
				.andExpect(jsonPath("$.points[0].weekStart").value("2024-12-30"));
	}

	@Test
	void rejectsInvalidRequestsBeforeCallingTheMlService() throws Exception {
		mockMvc.perform(post("/api/forecasts").contentType(MediaType.APPLICATION_JSON)
						.content("{\"skuId\":\"\",\"regionId\":\"R1\",\"asOf\":\"2024-12-30\",\"horizonWeeks\":99}"))
				.andExpect(status().isBadRequest())
				.andExpect(jsonPath("$.code").value("VALIDATION_FAILED"))
				.andExpect(jsonPath("$.violations.length()").value(2));
	}

	@Test
	void relaysMlServiceFailuresAsStructuredErrors() throws Exception {
		when(forecastClient.forecast(any()))
				.thenThrow(new MlServiceException(404, "UNKNOWN_SERIES", "no demand history for SKU-001 in R1"));

		mockMvc.perform(post("/api/forecasts").contentType(MediaType.APPLICATION_JSON).content(BODY))
				.andExpect(status().isNotFound())
				.andExpect(jsonPath("$.code").value("UNKNOWN_SERIES"))
				.andExpect(jsonPath("$.path").value("/api/forecasts"));
	}

}
