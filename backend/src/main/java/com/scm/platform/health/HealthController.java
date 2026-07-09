package com.scm.platform.health;

import com.scm.platform.config.ScmProperties;
import java.time.Instant;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RestController;

@RestController
@RequestMapping("/api/health")
public class HealthController {

	private final ScmProperties properties;

	public HealthController(ScmProperties properties) {
		this.properties = properties;
	}

	@GetMapping
	public HealthResponse health() {
		return new HealthResponse("UP", properties.serviceName(), properties.version(), Instant.now());
	}

	public record HealthResponse(String status, String service, String version, Instant timestamp) {
	}

}
