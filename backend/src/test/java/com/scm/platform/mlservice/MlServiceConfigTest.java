package com.scm.platform.mlservice;

import static org.assertj.core.api.Assertions.assertThat;

import com.scm.platform.config.ScmProperties;
import com.sun.net.httpserver.HttpServer;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.time.Duration;
import java.util.concurrent.atomic.AtomicReference;
import org.junit.jupiter.api.AfterEach;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.web.client.RestClient;

/** The real client, against a real local server, to see which headers actually go out. */
class MlServiceConfigTest {

	private HttpServer server;

	private final AtomicReference<String> seenToken = new AtomicReference<>();

	@BeforeEach
	void start() throws Exception {
		server = HttpServer.create(new InetSocketAddress("localhost", 0), 0);
		server.createContext("/ping", exchange -> {
			seenToken.set(exchange.getRequestHeaders().getFirst(MlServiceConfig.INTERNAL_TOKEN_HEADER));
			byte[] body = "ok".getBytes(StandardCharsets.UTF_8);
			exchange.sendResponseHeaders(200, body.length);
			exchange.getResponseBody().write(body);
			exchange.close();
		});
		server.start();
	}

	@AfterEach
	void stop() {
		server.stop(0);
	}

	private RestClient client(String token) {
		ScmProperties properties = new ScmProperties("scm", "1", "http://localhost:" + server.getAddress().getPort(),
				Duration.ofSeconds(5), token, new ScmProperties.Jobs(false, Duration.ofSeconds(1),
						Duration.ofMinutes(1), 3, Duration.ofSeconds(1)));
		return new MlServiceConfig().mlServiceRestClient(properties);
	}

	@Test
	void everyCallCarriesTheSharedSecretWhenOneIsConfigured() {
		client("a-shared-secret-long-enough").get().uri("/ping").retrieve().body(String.class);
		assertThat(seenToken.get()).isEqualTo("a-shared-secret-long-enough");
	}

	@Test
	void noHeaderIsSentWhenNoSecretIsConfigured() {
		client("").get().uri("/ping").retrieve().body(String.class);
		assertThat(seenToken.get()).isNull();
	}

}
