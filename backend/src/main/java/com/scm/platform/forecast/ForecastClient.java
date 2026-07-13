package com.scm.platform.forecast;

import com.scm.platform.forecast.ForecastDtos.ForecastRequest;
import com.scm.platform.forecast.ForecastDtos.ForecastResponse;

public interface ForecastClient {

	ForecastResponse forecast(ForecastRequest request);

}
