package com.agentcrashlab.mcp.common;

import java.util.Map;

import org.springframework.http.HttpStatus;

/**
 * REST API(공개·내부) 오류. 응답 본문은 {"error": {"code", "message"}}.
 */
public class ApiException extends RuntimeException {

	private final HttpStatus status;

	private final String code;

	private final Map<String, Object> details;

	public ApiException(HttpStatus status, String code, String message) {
		this(status, code, message, null);
	}

	/** details는 오류 봉투에 "details"로 함께 담긴다 */
	public ApiException(HttpStatus status, String code, String message, Map<String, Object> details) {
		super(message);
		this.status = status;
		this.code = code;
		this.details = details;
	}

	public HttpStatus status() {
		return this.status;
	}

	public String code() {
		return this.code;
	}

	public Map<String, Object> details() {
		return this.details;
	}

	public static ApiException notFound(String message) {
		return new ApiException(HttpStatus.NOT_FOUND, "NOT_FOUND", message);
	}

	public static ApiException conflict(String message) {
		return new ApiException(HttpStatus.CONFLICT, "CONFLICT", message);
	}

	public static ApiException badRequest(String code, String message) {
		return new ApiException(HttpStatus.BAD_REQUEST, code, message);
	}

	public static ApiException unauthorized() {
		return new ApiException(HttpStatus.UNAUTHORIZED, "UNAUTHORIZED", "Authentication required");
	}

	public static ApiException forbidden(String message) {
		return new ApiException(HttpStatus.FORBIDDEN, "PERMISSION_DENIED", message);
	}

}
