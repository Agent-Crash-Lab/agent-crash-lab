package com.agentcrashlab.mcp.auth;

import java.security.SecureRandom;
import java.util.Base64;

final class Tokens {

	private static final SecureRandom RANDOM = new SecureRandom();

	private Tokens() {
	}

	/** 32바이트 랜덤, URL-safe Base64. DB에는 Hashing.sha256 값만 저장한다 */
	static String generate() {
		byte[] bytes = new byte[32];
		RANDOM.nextBytes(bytes);
		return Base64.getUrlEncoder().withoutPadding().encodeToString(bytes);
	}

	/** "Bearer xxx" → "xxx". 형식이 다르면 null */
	static String bearer(String authorization) {
		if (authorization == null || !authorization.startsWith("Bearer ")) {
			return null;
		}
		String token = authorization.substring("Bearer ".length()).trim();
		return token.isEmpty() ? null : token;
	}

}
