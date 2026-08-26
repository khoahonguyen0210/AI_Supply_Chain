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

	public static final String INTERNAL_TOKEN_HEADER = "X-Internal-Token";

	@Bean
	RestClient mlServiceRestClient(ScmProperties properties) {
		// HTTP/1.1 only: the JDK client's default h2c upgrade makes the engine's server drop request bodies.
		HttpClient httpClient = HttpClient.newBuilder().version(HttpClient.Version.HTTP_1_1)
				.connectTimeout(Duration.ofSeconds(2)).build();
		JdkClientHttpRequestFactory factory = new JdkClientHttpRequestFactory(httpClient);
		// optimization, scenarios and agent runs are CPU-bound in the engine, so reads are allowed to be slow
		factory.setReadTimeout(properties.mlReadTimeout());
		RestClient.Builder builder = RestClient.builder().baseUrl(properties.mlServiceUrl()).requestFactory(factory);
		// The engine trusts the user named in a request, so it only answers callers holding this shared secret.
		if (!properties.mlInternalToken().isBlank()) {
			builder.defaultHeader(INTERNAL_TOKEN_HEADER, properties.mlInternalToken());
		}
		return builder.build();
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
