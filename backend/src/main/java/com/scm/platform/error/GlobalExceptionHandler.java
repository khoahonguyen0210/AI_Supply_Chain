package com.scm.platform.error;

import com.scm.platform.mlservice.MlServiceException;
import jakarta.servlet.http.HttpServletRequest;
import java.time.Instant;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.http.HttpStatus;
import org.springframework.http.HttpStatusCode;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;
import org.springframework.web.method.annotation.MethodArgumentTypeMismatchException;
import org.springframework.web.servlet.resource.NoResourceFoundException;

@RestControllerAdvice
public class GlobalExceptionHandler {

	private static final Logger log = LoggerFactory.getLogger(GlobalExceptionHandler.class);

	@ExceptionHandler(MethodArgumentNotValidException.class)
	public ResponseEntity<ApiError> handleValidation(MethodArgumentNotValidException ex, HttpServletRequest request) {
		List<ApiError.FieldViolation> violations = ex.getBindingResult().getFieldErrors().stream()
				.map(e -> new ApiError.FieldViolation(e.getField(), e.getDefaultMessage()))
				.toList();
		return build(HttpStatus.BAD_REQUEST, "VALIDATION_FAILED", "Request validation failed", request, violations);
	}

	@ExceptionHandler(RequestValidationException.class)
	public ResponseEntity<ApiError> handleRequestValidation(RequestValidationException ex,
			HttpServletRequest request) {
		return build(HttpStatus.BAD_REQUEST, "VALIDATION_FAILED", ex.getMessage(), request, ex.violations());
	}

	@ExceptionHandler(HttpMessageNotReadableException.class)
	public ResponseEntity<ApiError> handleUnreadable(HttpMessageNotReadableException ex,
			HttpServletRequest request) {
		return build(HttpStatus.BAD_REQUEST, "MALFORMED_REQUEST", "Request body is missing or not valid JSON",
				request, List.of());
	}

	@ExceptionHandler(MethodArgumentTypeMismatchException.class)
	public ResponseEntity<ApiError> handleBadParameter(MethodArgumentTypeMismatchException ex,
			HttpServletRequest request) {
		return build(HttpStatus.BAD_REQUEST, "INVALID_PARAMETER", "Invalid value for " + ex.getName(), request,
				List.of());
	}

	@ExceptionHandler(NoResourceFoundException.class)
	public ResponseEntity<ApiError> handleNotFound(NoResourceFoundException ex, HttpServletRequest request) {
		return build(HttpStatus.NOT_FOUND, "NOT_FOUND", "Resource not found", request, List.of());
	}

	@ExceptionHandler(ApiException.class)
	public ResponseEntity<ApiError> handleApi(ApiException ex, HttpServletRequest request) {
		return build(HttpStatusCode.valueOf(ex.status()), ex.code(), ex.getMessage(), request, List.of());
	}

	@ExceptionHandler(MlServiceException.class)
	public ResponseEntity<ApiError> handleMlService(MlServiceException ex, HttpServletRequest request) {
		return build(HttpStatusCode.valueOf(ex.status()), ex.code(), ex.getMessage(), request, List.of());
	}

	@ExceptionHandler(Exception.class)
	public ResponseEntity<ApiError> handleUnexpected(Exception ex, HttpServletRequest request) {
		log.error("Unhandled exception on {}", request.getRequestURI(), ex);
		return build(HttpStatus.INTERNAL_SERVER_ERROR, "INTERNAL_ERROR", "Unexpected server error", request,
				List.of());
	}

	private ResponseEntity<ApiError> build(HttpStatusCode status, String code, String message,
			HttpServletRequest request, List<ApiError.FieldViolation> violations) {
		ApiError body = new ApiError(Instant.now(), status.value(), code, message, request.getRequestURI(),
				violations);
		return ResponseEntity.status(status).body(body);
	}

}
