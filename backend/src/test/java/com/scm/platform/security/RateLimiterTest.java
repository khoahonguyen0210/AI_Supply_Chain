package com.scm.platform.security;

import static org.assertj.core.api.Assertions.assertThat;

import java.time.Clock;
import java.time.Duration;
import java.time.Instant;
import java.time.ZoneOffset;
import org.junit.jupiter.api.Test;

class RateLimiterTest {

	private static final class ManualClock extends Clock {

		private Instant now = Instant.parse("2025-01-01T00:00:00Z");

		void advance(Duration duration) {
			now = now.plus(duration);
		}

		@Override
		public java.time.ZoneId getZone() {
			return ZoneOffset.UTC;
		}

		@Override
		public Clock withZone(java.time.ZoneId zone) {
			return this;
		}

		@Override
		public Instant instant() {
			return now;
		}

	}

	@Test
	void allowsABurstUpToTheLimitThenRefuses() {
		RateLimiter limiter = new RateLimiter(new ManualClock());
		for (int i = 0; i < 5; i++) {
			assertThat(limiter.tryAcquire("k", 5).allowed()).as("request %d", i + 1).isTrue();
		}
		RateLimiter.Decision refused = limiter.tryAcquire("k", 5);
		assertThat(refused.allowed()).isFalse();
		assertThat(refused.retryAfterSeconds()).isBetween(1L, 13L); // 5 per minute: a token every 12 s
	}

	@Test
	void tokensComeBackAtTheConfiguredRate() {
		ManualClock clock = new ManualClock();
		RateLimiter limiter = new RateLimiter(clock);
		for (int i = 0; i < 60; i++) {
			limiter.tryAcquire("k", 60);
		}
		assertThat(limiter.tryAcquire("k", 60).allowed()).isFalse();

		clock.advance(Duration.ofSeconds(1)); // 60 per minute: one token per second
		assertThat(limiter.tryAcquire("k", 60).allowed()).isTrue();
		assertThat(limiter.tryAcquire("k", 60).allowed()).isFalse();

		clock.advance(Duration.ofSeconds(10));
		for (int i = 0; i < 10; i++) {
			assertThat(limiter.tryAcquire("k", 60).allowed()).isTrue();
		}
		assertThat(limiter.tryAcquire("k", 60).allowed()).isFalse();
	}

	@Test
	void anIdleBucketNeverHoldsMoreThanItsCapacity() {
		ManualClock clock = new ManualClock();
		RateLimiter limiter = new RateLimiter(clock);
		limiter.tryAcquire("k", 3);
		clock.advance(Duration.ofHours(5));
		for (int i = 0; i < 3; i++) {
			assertThat(limiter.tryAcquire("k", 3).allowed()).isTrue();
		}
		assertThat(limiter.tryAcquire("k", 3).allowed()).isFalse();
	}

	@Test
	void keysAreIndependent() {
		RateLimiter limiter = new RateLimiter(new ManualClock());
		assertThat(limiter.tryAcquire("a", 1).allowed()).isTrue();
		assertThat(limiter.tryAcquire("a", 1).allowed()).isFalse();
		assertThat(limiter.tryAcquire("b", 1).allowed()).isTrue();
	}

	@Test
	void theRetryHintShrinksAsTimePasses() {
		ManualClock clock = new ManualClock();
		RateLimiter limiter = new RateLimiter(clock);
		limiter.tryAcquire("k", 1);
		long first = limiter.tryAcquire("k", 1).retryAfterSeconds();
		clock.advance(Duration.ofSeconds(30));
		long later = limiter.tryAcquire("k", 1).retryAfterSeconds();
		assertThat(later).isLessThan(first);
	}

}
