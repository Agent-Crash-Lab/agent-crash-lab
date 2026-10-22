package com.agentcrashlab.mcp.publicapi;

import java.net.http.HttpClient;
import java.time.Duration;

import jakarta.servlet.http.HttpServletRequest;
import org.springframework.http.HttpHeaders;
import org.springframework.http.HttpMethod;
import org.springframework.http.HttpStatus;
import org.springframework.http.MediaType;
import org.springframework.http.ResponseEntity;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestHeader;
import org.springframework.web.bind.annotation.RestController;
import org.springframework.web.client.ResourceAccessException;
import org.springframework.web.client.RestClient;

import com.agentcrashlab.mcp.auth.CurrentUser;
import com.agentcrashlab.mcp.auth.UserSessions;
import com.agentcrashlab.mcp.common.ApiException;
import com.agentcrashlab.mcp.common.CrashLabProperties;

/** Public JSON gateway. Identity headers come exclusively from the authenticated session. */
@RestController
class RunGatewayController {
    private final UserSessions sessions;
    private final RestClient rest;
    private final String internalToken;

    RunGatewayController(UserSessions sessions, CrashLabProperties properties) {
        this.sessions = sessions;
        this.internalToken = properties.internalApiToken();
        JdkClientHttpRequestFactory factory = new JdkClientHttpRequestFactory(
                HttpClient.newBuilder().connectTimeout(Duration.ofSeconds(3)).build());
        // Initial design plus one bounded repair may make four sequential model calls.
        factory.setReadTimeout(Duration.ofSeconds(180));
        this.rest = RestClient.builder().baseUrl(properties.harnessUrl()).requestFactory(factory).build();
    }

    @GetMapping({"/api/scenarios", "/api/runs", "/api/runs/{runId}", "/api/runs/{runId}/events", "/api/comparisons", "/api/qa/target", "/api/qa/targets", "/api/qa/plans/{planId}", "/api/qa/batches", "/api/qa/batches/{batchId}", "/api/qa/registrations", "/api/qa/registrations/{profileId}"})
    ResponseEntity<byte[]> read(HttpServletRequest request,
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String authorization) {
        return forward(request, authorization, null);
    }

    @PostMapping({"/api/runs", "/api/qa/plans", "/api/qa/design", "/api/qa/batches", "/api/qa/batches/{batchId}/stop", "/api/qa/registrations", "/api/qa/registrations/{profileId}/design", "/api/qa/runs/{runId}/approval", "/api/qa/runs/{runId}/follow-up"})
    ResponseEntity<byte[]> start(HttpServletRequest request,
            @RequestHeader(value = HttpHeaders.AUTHORIZATION, required = false) String authorization,
            @RequestBody String body) {
        return forward(request, authorization, body);
    }

    private ResponseEntity<byte[]> forward(HttpServletRequest request, String authorization, String body) {
        CurrentUser user = this.sessions.require(authorization);
        if ("POST".equals(request.getMethod()) && !(request.getRequestURI().matches("/api/qa/runs/[^/]+/approval") ? user.hasRole("APPROVER") : user.hasRole(CurrentUser.REQUESTER))) {
            throw ApiException.forbidden("REQUESTER role required");
        }
        if (this.internalToken == null || this.internalToken.isBlank()) {
            throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "GATEWAY_NOT_CONFIGURED", "Internal token required");
        }
        // JSON polling is used by the console; never buffer an unbounded SSE response here.
        String target = request.getRequestURI() + (request.getQueryString() == null ? "" : "?" + request.getQueryString());
        try {
            var outgoing = this.rest.method(HttpMethod.valueOf(request.getMethod())).uri(target)
                    .header("X-Internal-Token", this.internalToken)
                    .header("X-User-Id", user.userId()).header("X-User-Roles", String.join(",", user.roles()))
                    .accept(MediaType.APPLICATION_JSON);
            if (body != null) outgoing.contentType(MediaType.APPLICATION_JSON).body(body);
            return outgoing.exchange((sent, response) -> ResponseEntity.status(response.getStatusCode())
                    .contentType(MediaType.APPLICATION_JSON).header(HttpHeaders.CACHE_CONTROL, "no-store")
                    .body(response.getBody().readAllBytes()));
        }
        catch (ResourceAccessException ex) {
            throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "HARNESS_UNAVAILABLE", "Harness connection failed");
        }
    }
}
