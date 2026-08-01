package com.scm.platform.error;

import java.util.List;

public class RequestValidationException extends RuntimeException {

	private final transient List<ApiError.FieldViolation> violations;

	public RequestValidationException(String message, List<ApiError.FieldViolation> violations) {
		super(message);
		this.violations = List.copyOf(violations);
	}

	public List<ApiError.FieldViolation> violations() {
		return violations;
	}

}
