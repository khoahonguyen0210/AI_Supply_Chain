package com.scm.platform.forecast;

import com.scm.platform.forecast.ForecastDtos.ForecastRequest;
import com.scm.platform.forecast.ForecastDtos.ForecastResponse;
import jakarta.validation.Valid;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/forecasts")
public class ForecastController {

	private final ForecastClient forecastClient;

	public ForecastController(ForecastClient forecastClient) {
		this.forecastClient = forecastClient;
	}

	@PostMapping
	public ForecastResponse forecast(@Valid @RequestBody ForecastRequest request) {
		return forecastClient.forecast(request);
	}

}
