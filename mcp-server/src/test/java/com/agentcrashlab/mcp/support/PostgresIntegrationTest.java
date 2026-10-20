package com.agentcrashlab.mcp.support;

import java.nio.file.Path;
import java.sql.Connection;
import java.sql.DriverManager;
import java.sql.SQLException;

import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.context.bean.override.mockito.MockitoBean;
import org.testcontainers.postgresql.PostgreSQLContainer;
import org.testcontainers.utility.DockerImageName;
import org.testcontainers.utility.MountableFile;

import com.agentcrashlab.mcp.harness.HarnessClient;

/**
 * 실제 Postgres로 검증하는 테스트의 공통 설정.
 * compose와 같은 이미지·init.sql·계정을 쓰고, 앱은 mcp_app으로 접속해 Flyway를 실행한다.
 * 컨테이너는 테스트 JVM에서 한 번만 띄워 여러 테스트 클래스가 공유한다.
 */
@SpringBootTest
public abstract class PostgresIntegrationTest {

	protected static final String DATABASE = "crashlab";

	protected static final String MCP_PASSWORD = "mcp";

	protected static final String ORACLE_PASSWORD = "oracle";

	protected static final String INTERNAL_TOKEN = "test-internal-token";

	protected static final String DEMO_PASSWORD = "test-password";

	protected static final PostgreSQLContainer POSTGRES = new PostgreSQLContainer(DockerImageName.parse("postgres:16"))
		.withDatabaseName(DATABASE)
		.withUsername("postgres")
		.withPassword("postgres")
		.withEnv("MCP_DB_PASSWORD", MCP_PASSWORD)
		.withEnv("HARNESS_DB_PASSWORD", "harness")
		.withEnv("ORACLE_DB_PASSWORD", ORACLE_PASSWORD)
		.withCopyFileToContainer(MountableFile.forHostPath(Path.of("../infra/postgres/init.sql")),
				"/docker-entrypoint-initdb.d/init.sql");

	static {
		POSTGRES.start();
	}

	/** Harness는 아직 없으므로 가짜로 둔다. 재개 요청·이벤트 제출은 이 mock으로 확인한다 */
	@MockitoBean
	protected HarnessClient harness;

	@DynamicPropertySource
	static void datasource(DynamicPropertyRegistry registry) {
		registry.add("spring.datasource.url", POSTGRES::getJdbcUrl);
		registry.add("spring.datasource.username", () -> "mcp_app");
		registry.add("spring.datasource.password", () -> MCP_PASSWORD);
		registry.add("crashlab.internal-api-token", () -> INTERNAL_TOKEN);
		registry.add("crashlab.demo-user-password", () -> DEMO_PASSWORD);
	}

	/** Oracle과 같은 권한으로 접속한다 (harness의 ORACLE_DATABASE_URL). */
	protected static Connection connectAsOracle() throws SQLException {
		return DriverManager.getConnection(POSTGRES.getJdbcUrl(), "oracle_ro", ORACLE_PASSWORD);
	}

}
