package com.scm.platform.mlservice;

import com.scm.platform.config.ScmProperties;
import com.scm.platform.forecast.ForecastClient;
import com.scm.platform.forecast.PythonForecastClient;
import java.net.http.HttpClient;
import java.time.Duration;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.web.client.RestClient;

@Configuration(proxyBeanMethods = false)
public class MlServiceConfig {

	@Bean
	RestClient mlServiceRestClient(ScmProperties properties) {
		HttpClient httpClient = HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(2)).build();
		JdkClientHttpRequestFactory factory = new JdkClientHttpRequestFactory(httpClient);
		// optimization, scenarios and agent runs are CPU-bound in the engine, so reads are allowed to be slow
		factory.setReadTimeout(properties.mlReadTimeout());
		return RestClient.builder().baseUrl(properties.mlServiceUrl()).requestFactory(factory).build();
	}

	@Bean
	MlEngineClient mlEngineClient(RestClient mlServiceRestClient) {
		return new PythonEngineClient(mlServiceRestClient);
	}

	@Bean
	ForecastClient forecastClient(RestClient mlServiceRestClient) {
		return new PythonForecastClient(mlServiceRestClient);
	}

}
