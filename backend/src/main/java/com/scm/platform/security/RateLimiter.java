package com.scm.platform.security;

import java.time.Clock;
import java.util.concurrent.ConcurrentHashMap;

/** Token bucket per key; state is per process. */
public class RateLimiter {

	private static final int PURGE_ABOVE = 10_000;

	private static final long IDLE_NANOS = 10L * 60 * 1_000_000_000L;

	public record Decision(boolean allowed, long retryAfterSeconds) {
	}

	private static final class Bucket {

		double tokens;

		long updatedNanos;

		Bucket(double tokens, long updatedNanos) {
			this.tokens = tokens;
			this.updatedNanos = updatedNanos;
		}

	}

	private final ConcurrentHashMap<String, Bucket> buckets = new ConcurrentHashMap<>();

	private final Clock clock;

	public RateLimiter(Clock clock) {
		this.clock = clock;
	}

	public Decision tryAcquire(String key, int perMinute) {
		long now = nanos();
		if (buckets.size() > PURGE_ABOVE) {
			buckets.values().removeIf(bucket -> now - bucket.updatedNanos > IDLE_NANOS);
		}
		Bucket bucket = buckets.computeIfAbsent(key, k -> new Bucket(perMinute, now));
		synchronized (bucket) {
			double perNano = perMinute / 60.0 / 1_000_000_000.0;
			bucket.tokens = Math.min(perMinute, bucket.tokens + (now - bucket.updatedNanos) * perNano);
			bucket.updatedNanos = now;
			if (bucket.tokens >= 1) {
				bucket.tokens -= 1;
				return new Decision(true, 0);
			}
			long wait = (long) Math.ceil((1 - bucket.tokens) / perNano / 1_000_000_000.0);
			return new Decision(false, Math.max(1, wait));
		}
	}

	private long nanos() {
		return clock.millis() * 1_000_000L;
	}

}
