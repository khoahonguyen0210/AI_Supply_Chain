package com.scm.platform.job;

import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.boot.autoconfigure.condition.ConditionalOnProperty;
import org.springframework.scheduling.annotation.Scheduled;
import org.springframework.stereotype.Component;

@Component
@ConditionalOnProperty(name = "scm.jobs.worker-enabled", havingValue = "true", matchIfMissing = true)
public class JobWorkerScheduler {

	private static final Logger log = LoggerFactory.getLogger(JobWorkerScheduler.class);

	private final JobWorker worker;

	public JobWorkerScheduler(JobWorker worker) {
		this.worker = worker;
	}

	@Scheduled(fixedDelayString = "${scm.jobs.poll-interval:1s}")
	public void poll() {
		try {
			worker.drain();
		}
		catch (RuntimeException ex) {
			// a database outage must not kill the polling thread; the next tick tries again
			log.error("job polling failed", ex);
		}
	}

}
