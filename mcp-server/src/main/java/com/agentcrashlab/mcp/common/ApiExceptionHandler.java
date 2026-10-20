package com.agentcrashlab.mcp.common;

import java.util.Map;

import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.http.converter.HttpMessageNotReadableException;
import org.springframework.web.bind.MethodArgumentNotValidException;
import org.springframework.web.bind.annotation.ExceptionHandler;
import org.springframework.web.bind.annotation.RestControllerAdvice;

@RestControllerAdvice
class ApiExceptionHandler {

	@ExceptionHandler(ApiException.class)
	ResponseEntity<Map<String, Object>> handle(ApiException ex) {
		return ResponseEntity.status(ex.status()).body(body(ex.code(), ex.getMessage()));
	}

	@ExceptionHandler({ MethodArgumentNotValidException.class, HttpMessageNotReadableException.class })
	ResponseEntity<Map<String, Object>> handleInvalidBody(Exception ex) {
		return ResponseEntity.status(HttpStatus.BAD_REQUEST).body(body("VALIDATION_ERROR", "Invalid request body"));
	}

	static Map<String, Object> body(String code, String message) {
		return Map.of("error", Map.of("code", code, "message", message));
	}

}
