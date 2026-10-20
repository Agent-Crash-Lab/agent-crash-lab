package com.agentcrashlab.mcp.auth;

import java.io.IOException;
import java.nio.charset.StandardCharsets;
import java.security.MessageDigest;

import jakarta.servlet.FilterChain;
import jakarta.servlet.ServletException;
import jakarta.servlet.http.HttpServletRequest;
import jakarta.servlet.http.HttpServletResponse;

import org.springframework.boot.web.servlet.FilterRegistrationBean;
import org.springframework.context.annotation.Bean;
import org.springframework.context.annotation.Configuration;
import org.springframework.http.MediaType;
import org.springframework.web.filter.OncePerRequestFilter;

import com.agentcrashlab.mcp.common.CrashLabProperties;

/**
 * /internal/** 는 X-Internal-Token이 설정값과 같을 때만 통과한다.
 * 설정값이 비어 있으면 모두 거부한다 (토큰 없이 열리는 일이 없도록).
 */
class InternalTokenFilter extends OncePerRequestFilter {

	static final String HEADER = "X-Internal-Token";

	private final byte[] expected;

	InternalTokenFilter(String expected) {
		this.expected = (expected == null) ? new byte[0] : expected.getBytes(StandardCharsets.UTF_8);
	}

	@Override
	protected void doFilterInternal(HttpServletRequest request, HttpServletResponse response, FilterChain chain)
			throws ServletException, IOException {
		if (this.expected.length == 0) {
			reject(response, HttpServletResponse.SC_SERVICE_UNAVAILABLE, "UNAVAILABLE", "Internal API token is not configured");
			return;
		}
		String actual = request.getHeader(HEADER);
		if (actual == null || !MessageDigest.isEqual(this.expected, actual.getBytes(StandardCharsets.UTF_8))) {
			reject(response, HttpServletResponse.SC_UNAUTHORIZED, "UNAUTHORIZED", "Invalid internal token");
			return;
		}
		chain.doFilter(request, response);
	}

	private static void reject(HttpServletResponse response, int status, String code, String message) throws IOException {
		response.setStatus(status);
		response.setContentType(MediaType.APPLICATION_JSON_VALUE);
		response.setCharacterEncoding(StandardCharsets.UTF_8.name());
		response.getWriter().write("{\"error\":{\"code\":\"%s\",\"message\":\"%s\"}}".formatted(code, message));
	}

	@Configuration(proxyBeanMethods = false)
	static class Registration {

		@Bean
		FilterRegistrationBean<InternalTokenFilter> internalTokenFilter(CrashLabProperties properties) {
			FilterRegistrationBean<InternalTokenFilter> registration = new FilterRegistrationBean<>(
					new InternalTokenFilter(properties.internalApiToken()));
			registration.addUrlPatterns("/internal/*");
			return registration;
		}

	}

}
