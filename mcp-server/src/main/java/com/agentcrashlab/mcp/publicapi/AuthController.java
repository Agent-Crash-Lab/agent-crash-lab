package com.agentcrashlab.mcp.publicapi;

import java.time.Instant;
import java.util.List;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;

import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RestController;

import com.agentcrashlab.mcp.auth.UserSessions;

/** 공개 API 로그인 (MCP_SPEC 5.3) */
@RestController
class AuthController {

	private final UserSessions sessions;

	AuthController(UserSessions sessions) {
		this.sessions = sessions;
	}

	record LoginBody(@NotBlank String userId, @NotBlank String password) {
	}

	record LoginResponse(String accessToken, String tokenType, Instant expiresAt, String userId, List<String> roles) {
	}

	@PostMapping("/api/auth/login")
	LoginResponse login(@Valid @RequestBody LoginBody body) {
		UserSessions.Session session = this.sessions.login(body.userId(), body.password());
		return new LoginResponse(session.token(), "Bearer", session.expiresAt(), session.user().userId(),
				session.user().roles());
	}

}
