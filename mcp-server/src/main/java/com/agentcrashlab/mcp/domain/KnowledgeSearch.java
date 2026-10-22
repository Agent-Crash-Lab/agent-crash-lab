package com.agentcrashlab.mcp.domain;

import java.net.http.HttpClient;
import java.time.Duration;
import java.util.Map;
import java.util.Set;

import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import org.springframework.beans.factory.annotation.Value;
import org.springframework.http.HttpStatus;
import org.springframework.http.client.JdkClientHttpRequestFactory;
import org.springframework.web.bind.annotation.*;
import org.springframework.web.client.RestClient;
import com.agentcrashlab.mcp.auth.UserSessions;
import com.agentcrashlab.mcp.common.ApiException;
import com.agentcrashlab.mcp.common.CrashLabProperties;

/** One authenticated boundary for console, Harness planning and MCP retrieval. */
@RestController
public class KnowledgeSearch {
    private final RestClient rest;
    private final UserSessions sessions;

    public KnowledgeSearch(@Value("${KNOWLEDGE_URL:http://knowledge:8010}") String url,
                           CrashLabProperties properties, UserSessions sessions) {
        var factory = new JdkClientHttpRequestFactory(HttpClient.newBuilder()
                .connectTimeout(Duration.ofSeconds(2)).build());
        factory.setReadTimeout(Duration.ofSeconds(8));
        this.rest = RestClient.builder().baseUrl(url).requestFactory(factory)
                .defaultHeader("X-Internal-Token", properties.internalApiToken()).build();
        this.sessions = sessions;
    }

    public record Query(@NotBlank @Size(max=1000) String query, String targetType, Integer limit, String sourceType, String riskType) {}

    @SuppressWarnings("unchecked")
    public Map<String,Object> search(String query, String targetType, Integer limit) {
        return search(query, targetType, limit, null, null);
    }

    @SuppressWarnings("unchecked")
    public Map<String,Object> search(String query, String targetType, Integer limit, String sourceType, String riskType) {
        String kind = targetType == null ? "COMMON" : targetType;
        String category = sourceType == null ? "ALL" : sourceType;
        if (!Set.of("ALL","RESEARCH","INCIDENT","TECHNICAL","PROJECT_POLICY").contains(category)
                || (riskType != null && (riskType.isBlank() || riskType.length()>64)))
            throw ApiException.badRequest("VALIDATION_ERROR", "Invalid evidence filter");
        int count = limit == null ? 3 : limit;
        if (query == null || query.strip().length()<2 || query.length()>1000 || count<1 || count>5
                || !Set.of("COMMON","PURCHASE","PRODUCTION","QUALITY").contains(kind))
            throw ApiException.badRequest("VALIDATION_ERROR", "Invalid knowledge query");
        try {
            var body = new java.util.HashMap<String,Object>();
            body.put("query", query); body.put("target_type", kind); body.put("limit", count);
            body.put("source_type", category);
            if (riskType != null) body.put("risk_type", riskType);
            return this.rest.post().uri("/internal/knowledge/search")
                    .body(body)
                    .retrieve().body(Map.class);
        } catch (Exception ex) {
            throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "KNOWLEDGE_UNAVAILABLE",
                    "Knowledge search is unavailable or not indexed");
        }
    }

    @PostMapping("/api/knowledge/search")
    Map<String,Object> publicSearch(@RequestHeader(value="Authorization",required=false) String authorization,
                                    @Valid @RequestBody Query query) {
        this.sessions.require(authorization);
        return search(query.query(), query.targetType(), query.limit(), query.sourceType(), query.riskType());
    }

    @PostMapping("/internal/knowledge/search")
    Map<String,Object> internalSearch(@Valid @RequestBody Query query) {
        return search(query.query(), query.targetType(), query.limit(), query.sourceType(), query.riskType());
    }

    @GetMapping("/api/knowledge/status")
    @SuppressWarnings("unchecked")
    Map<String,Object> publicStatus(@RequestHeader(value="Authorization",required=false) String authorization) {
        this.sessions.require(authorization);
        try {
            return this.rest.get().uri("/internal/knowledge/status").retrieve().body(Map.class);
        } catch (Exception ex) {
            throw new ApiException(HttpStatus.SERVICE_UNAVAILABLE, "KNOWLEDGE_UNAVAILABLE", "Knowledge service unavailable");
        }
    }
}
