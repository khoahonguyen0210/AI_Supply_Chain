package com.scm.platform.observability;

import io.micrometer.core.instrument.Counter;
import io.micrometer.core.instrument.MeterRegistry;
import io.micrometer.core.instrument.Timer;
import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;
import java.io.IOException;
import java.time.Duration;
import java.util.concurrent.TimeUnit;
import org.springframework.core.Ordered;
import org.springframework.core.annotation.Order;
import org.springframework.stereotype.Component;
import org.springframework.web.filter.OncePerRequestFilter;

/**
 * Times every API request and counts its outcome. One untagged timer carries the p50/p95/p99 (percentiles
 * cannot be merged across tags), and a counter per status class gives throughput and error rate.
 */
@Component
@Order(Ordered.HIGHEST_PRECEDENCE)
public class RequestMetricsFilter extends OncePerRequestFilter {

	public static final String DURATION = "scm.api.request.duration";

	public static final String REQUESTS = "scm.api.requests";

	private final Timer timer;

	private final Counter ok;

	private final Counter clientErrors;

	private final Counter serverErrors;

	public RequestMetricsFilter(MeterRegistry registry) {
		this.timer = Timer.builder(DURATION).description("API request latency")
				.publishPercentiles(0.5, 0.95, 0.99).register(registry);
		this.ok = Counter.builder(REQUESTS).tag("status", "2xx-3xx").register(registry);
		this.clientErrors = Counter.builder(REQUESTS).tag("status", "4xx").register(registry);
		this.serverErrors = Counter.builder(REQUESTS).tag("status", "5xx").register(registry);
	}

	@Override
	protected boolean shouldNotFilter(HttpServletRequest request) {
		return !request.getRequestURI().startsWith("/api/");
	}

	@Override
	protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
			throws ServletException, IOException {
		long start = System.nanoTime();
		int status = 500;
		try {
			chain.doFilter(request, response);
			status = response.getStatus();
		}
		finally {
			timer.record(System.nanoTime() - start, TimeUnit.NANOSECONDS);
			if (status >= 500) {
				serverErrors.increment();
			}
			else if (status >= 400) {
				clientErrors.increment();
			}
			else {
				ok.increment();
			}
		}
	}

	public Duration percentile(double fraction) {
		for (var value : timer.takeSnapshot().percentileValues()) {
			if (Math.abs(value.percentile() - fraction) < 1e-9) {
				return Duration.ofNanos((long) value.value(TimeUnit.NANOSECONDS));
			}
		}
		return Duration.ZERO;
	}

	public long total() {
		return timer.count();
	}

	public long serverErrors() {
		return (long) serverErrors.count();
	}

	public long clientErrors() {
		return (long) clientErrors.count();
	}

}
