package com.agentcrashlab.mcp.publicapi;

import static org.assertj.core.api.Assertions.assertThat;
import static org.assertj.core.api.Assertions.assertThatThrownBy;
import static org.mockito.Mockito.*;

import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.util.List;
import java.util.concurrent.atomic.AtomicReference;
import com.sun.net.httpserver.HttpServer;
import org.junit.jupiter.api.Test;
import org.springframework.mock.web.MockHttpServletRequest;
import com.agentcrashlab.mcp.auth.CurrentUser;
import com.agentcrashlab.mcp.auth.UserSessions;
import com.agentcrashlab.mcp.common.ApiException;
import com.agentcrashlab.mcp.common.CrashLabProperties;

class RunGatewayTests {
    @Test
    void forwardsTrustedIdentityAndPreservesUpstreamStatusAndQuery() throws Exception {
        HttpServer upstream = HttpServer.create(new InetSocketAddress("127.0.0.1", 0), 0);
        AtomicReference<String> identity = new AtomicReference<>();
        upstream.createContext("/api/runs", exchange -> {
            identity.set(exchange.getRequestHeaders().getFirst("X-User-Id") + ":"
                    + exchange.getRequestHeaders().getFirst("X-User-Roles") + ":"
                    + exchange.getRequestHeaders().getFirst("X-Internal-Token") + ":" + exchange.getRequestURI());
            byte[] body = "{\"error\":{\"code\":\"RUN_IN_PROGRESS\"}}".getBytes(StandardCharsets.UTF_8);
            exchange.sendResponseHeaders(409, body.length);
            exchange.getResponseBody().write(body);exchange.close();
        });
        upstream.start();
        try {
            UserSessions sessions=mock(UserSessions.class);
            when(sessions.require("Bearer user")).thenReturn(new CurrentUser("requester-01",List.of("REQUESTER"),"ORG"));
            var properties=new CrashLabProperties("internal-secret","http://127.0.0.1:"+upstream.getAddress().getPort(),null,null,null,null,null,null,null);
            var gateway=new RunGatewayController(sessions,properties);
            var request=new MockHttpServletRequest("GET","/api/runs");request.setQueryString("limit=2");
            request.addHeader("X-User-Id","forged");request.addHeader("X-Internal-Token","forged");
            var result=gateway.read(request,"Bearer user");
            assertThat(result.getStatusCode().value()).isEqualTo(409);
            assertThat(new String(result.getBody(),StandardCharsets.UTF_8)).contains("RUN_IN_PROGRESS").doesNotContain("secret");
            assertThat(identity.get()).isEqualTo("requester-01:REQUESTER:internal-secret:/api/runs?limit=2");
        } finally {upstream.stop(0);}
    }
    @Test
    void rejectsMissingSessionAndReadOnlyUsersBeforeStarting() {
        UserSessions sessions=mock(UserSessions.class);
        when(sessions.require(null)).thenThrow(ApiException.unauthorized());
        when(sessions.require("Bearer approver")).thenReturn(new CurrentUser("approver-01",List.of("APPROVER"),"ORG"));
        var properties=new CrashLabProperties("secret","http://127.0.0.1:1",null,null,null,null,null,null,null);
        var gateway=new RunGatewayController(sessions,properties);
        assertThatThrownBy(()->gateway.read(new MockHttpServletRequest("GET","/api/runs"),null)).isInstanceOf(ApiException.class);
        assertThatThrownBy(()->gateway.start(new MockHttpServletRequest("POST","/api/runs"),"Bearer approver","{}"))
                .isInstanceOf(ApiException.class).hasMessage("REQUESTER role required");
    }
}
