package com.agentcrashlab.mcp.domain;

import java.io.IOException;
import java.nio.file.Files;
import java.nio.file.Path;
import java.util.ArrayList;
import java.util.Comparator;
import java.util.LinkedHashMap;
import java.util.List;
import java.util.Locale;
import java.util.Map;
import java.util.Optional;

import com.fasterxml.jackson.annotation.JsonIgnoreProperties;
import org.springframework.boot.ApplicationArguments;
import org.springframework.boot.ApplicationRunner;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Component;

import com.agentcrashlab.mcp.common.CrashLabProperties;
import tools.jackson.databind.json.JsonMapper;

/**
 * 조사 지침 문서 (fixtures/drafts/manufacturing-qa/guides). 서버 시작 시 guide_document에 적재한다.
 * 검색은 키워드 일치 점수로 한다. 모델을 쓰지 않으므로 같은 질문에는 항상 같은 결과가 나온다.
 */
@Component
public class GuideLibrary implements ApplicationRunner {

	static final String GUIDE_DIR = "drafts/manufacturing-qa/guides";

	private static final int SNIPPET_LENGTH = 200;

	private final JdbcClient jdbc;

	private final JsonMapper json;

	private final Path guideDir;

	GuideLibrary(JdbcClient jdbc, JsonMapper json, CrashLabProperties properties) {
		this.jdbc = jdbc;
		this.json = json;
		this.guideDir = Path.of(properties.fixturesDir()).resolve(GUIDE_DIR);
	}

	@JsonIgnoreProperties(ignoreUnknown = true)
	public record IndexEntry(String documentId, String version, String title, String bodyPath) {
	}

	@JsonIgnoreProperties(ignoreUnknown = true)
	record Index(List<IndexEntry> documents) {
	}

	public record Guide(String documentId, String version, String title, String body) {

		public String resourceUri() {
			return "guide://%s/%s".formatted(this.documentId, this.version);
		}

	}

	/** guides/index.json 목록. Resource 등록에 쓴다 */
	public List<IndexEntry> index() {
		try {
			return this.json.readValue(Files.readString(this.guideDir.resolve("index.json")), Index.class).documents();
		}
		catch (IOException ex) {
			throw new IllegalStateException("Cannot read guide index: " + this.guideDir, ex);
		}
	}

	@Override
	public void run(ApplicationArguments args) throws IOException {
		for (IndexEntry entry : index()) {
			String body = Files.readString(this.guideDir.resolve(entry.bodyPath()));
			this.jdbc.sql("""
					INSERT INTO guide_document (document_id, version, title, body) VALUES (?, ?, ?, ?)
					ON CONFLICT (document_id, version) DO UPDATE
					SET title = EXCLUDED.title, body = EXCLUDED.body, loaded_at = now()""")
				.params(entry.documentId(), entry.version(), entry.title(), body)
				.update();
		}
	}

	public Optional<Guide> find(String documentId, String version) {
		return this.jdbc.sql("SELECT document_id, version, title, body FROM guide_document WHERE document_id = ? AND version = ?")
			.params(documentId, version)
			.query(Guide.class)
			.optional();
	}

	/**
	 * 질문을 공백 기준 단어로 나눠, 제목 일치는 3점·본문 일치는 1점으로 센다. 점수가 있는 문서만 높은 순으로 돌려준다.
	 * location은 가장 많이 일치한 문단 번호, snippet은 그 문단의 앞부분이다.
	 */
	public List<Map<String, Object>> search(String query, int limit) {
		List<String> terms = List.of(query.toLowerCase(Locale.ROOT).split("[\\s,.·/]+"))
			.stream()
			.filter(term -> !term.isBlank())
			.toList();
		List<Guide> guides = this.jdbc.sql("SELECT document_id, version, title, body FROM guide_document ORDER BY document_id")
			.query(Guide.class)
			.list();

		record Scored(Guide guide, int score, int paragraph, String snippet) {
		}
		List<Scored> scored = new ArrayList<>();
		for (Guide guide : guides) {
			int score = 3 * hits(guide.title(), terms);
			List<String> paragraphs = paragraphs(guide.body());
			int best = -1;
			int bestHits = 0;
			for (int i = 0; i < paragraphs.size(); i++) {
				int paragraphHits = hits(paragraphs.get(i), terms);
				score += paragraphHits;
				if (paragraphHits > bestHits) {
					best = i;
					bestHits = paragraphHits;
				}
			}
			if (score > 0) {
				String text = (best >= 0) ? paragraphs.get(best) : paragraphs.get(0);
				scored.add(new Scored(guide, score, best + 1, text.substring(0, Math.min(SNIPPET_LENGTH, text.length()))));
			}
		}
		return scored.stream()
			.sorted(Comparator.comparingInt(Scored::score).reversed().thenComparing(s -> s.guide().documentId()))
			.limit(limit)
			.map(s -> {
				Map<String, Object> result = new LinkedHashMap<>();
				result.put("document_id", s.guide().documentId());
				result.put("version", s.guide().version());
				result.put("title", s.guide().title());
				result.put("location", (s.paragraph() > 0) ? "문단 " + s.paragraph() : "전체");
				result.put("snippet", s.snippet());
				result.put("resource_uri", s.guide().resourceUri());
				return result;
			})
			.toList();
	}

	/** 제목 줄(#)을 뺀 본문 문단 */
	private static List<String> paragraphs(String body) {
		return List.of(body.split("\\n\\s*\\n"))
			.stream()
			.map(String::trim)
			.filter(p -> !p.isEmpty() && !p.startsWith("#"))
			.toList();
	}

	private static int hits(String text, List<String> terms) {
		String lower = text.toLowerCase(Locale.ROOT);
		int count = 0;
		for (String term : terms) {
			int from = 0;
			while ((from = lower.indexOf(term, from)) >= 0) {
				count++;
				from += term.length();
			}
		}
		return count;
	}

}
