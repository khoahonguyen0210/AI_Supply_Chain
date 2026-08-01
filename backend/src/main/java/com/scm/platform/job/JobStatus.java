package com.scm.platform.job;

public enum JobStatus {

	QUEUED,
	RUNNING,
	SUCCEEDED,
	FAILED;

	public boolean isTerminal() {
		return this == SUCCEEDED || this == FAILED;
	}

}
