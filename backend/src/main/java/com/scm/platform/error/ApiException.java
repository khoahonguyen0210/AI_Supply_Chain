package com.scm.platform.error;

public class ApiException extends RuntimeException {

	private final int status;

	private final String code;

	public ApiException(int status, String code, String message) {
		super(message);
		this.status = status;
		this.code = code;
	}

	public int status() {
		return status;
	}

	public String code() {
		return code;
	}

	public static ApiException unauthenticated(String message) {
		return new ApiException(401, "UNAUTHENTICATED", message);
	}

	public static ApiException forbidden(String message) {
		return new ApiException(403, "FORBIDDEN", message);
	}

	public static ApiException notFound(String code, String message) {
		return new ApiException(404, code, message);
	}

	public static ApiException conflict(String code, String message) {
		return new ApiException(409, code, message);
	}

	public static ApiException badRequest(String code, String message) {
		return new ApiException(400, code, message);
	}

}
