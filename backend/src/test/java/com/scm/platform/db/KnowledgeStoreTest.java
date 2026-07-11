package com.scm.platform.db;

import static org.assertj.core.api.Assertions.assertThat;

import com.scm.platform.support.PostgresContainerConfig;
import java.util.List;
import java.util.Map;
import java.util.stream.Collectors;
import java.util.stream.IntStream;
import org.junit.jupiter.api.BeforeEach;
import org.junit.jupiter.api.Test;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.context.annotation.Import;
import org.springframework.jdbc.core.simple.JdbcClient;

@SpringBootTest
@Import(PostgresContainerConfig.class)
class KnowledgeStoreTest {

	private static final int DIMENSION = 384;

	private static final String FILTERED_SEARCH = """
			SELECT c.document_id
			FROM knowledge_chunk c
			JOIN knowledge_document d
			  ON d.document_id = c.document_id AND d.version = c.document_version
			WHERE d.effective_date <= :asOf
			  AND (d.expiry_date IS NULL OR d.expiry_date >= :asOf)
			  AND d.allowed_roles && CAST(:roles AS text[])
			ORDER BY c.embedding <=> CAST(:query AS vector)
			LIMIT 10
			""";

	@Autowired
	private JdbcClient jdbc;

	@BeforeEach
	void seed() {
		jdbc.sql("TRUNCATE knowledge_document CASCADE").update();
		insertDocument("DOC-CURRENT", "1", "2025-01-01", null, "{planner,admin}", 0);
		insertDocument("DOC-EXPIRED", "1", "2023-01-01", "2024-01-01", "{planner,admin}", 1);
		insertDocument("DOC-RESTRICTED", "1", "2025-01-01", null, "{admin}", 2);
	}

	private void insertDocument(String id, String version, String effective, String expiry, String roles, int axis) {
		jdbc.sql("""
				INSERT INTO knowledge_document
				  (document_id, version, doc_type, title, effective_date, expiry_date, allowed_roles, content, content_sha256)
				VALUES (:id, :version, 'POLICY', :id, CAST(:effective AS date), CAST(:expiry AS date),
				        CAST(:roles AS text[]), 'Payment terms are net 30 days.', repeat('0', 64))
				""")
				.param("id", id).param("version", version).param("effective", effective)
				.param("expiry", expiry).param("roles", roles).update();
		jdbc.sql("""
				INSERT INTO knowledge_chunk (document_id, document_version, chunk_index, content, token_count, embedding, metadata)
				VALUES (:id, :version, 0, 'Payment terms are net 30 days.', 7, CAST(:embedding AS vector), CAST(:meta AS jsonb))
				""")
				.param("id", id).param("version", version).param("embedding", vector(axis))
				.param("meta", "{\"section\": \"payment\"}").update();
	}

	private static String vector(int axis) {
		return IntStream.range(0, DIMENSION).mapToObj(i -> i == axis ? "1" : "0")
				.collect(Collectors.joining(",", "[", "]"));
	}

	@Test
	void nearestChunkIsReturnedFirst() {
		List<String> ids = jdbc.sql("""
				SELECT document_id FROM knowledge_chunk
				ORDER BY embedding <=> CAST(:query AS vector) LIMIT 1
				""").param("query", vector(2)).query(String.class).list();
		assertThat(ids).containsExactly("DOC-RESTRICTED");
	}

	@Test
	void expiredAndUnauthorizedDocumentsAreFilteredOut() {
		List<String> visible = jdbc.sql(FILTERED_SEARCH)
				.params(Map.of("asOf", java.sql.Date.valueOf("2025-06-01"), "roles", "{planner}", "query", vector(1)))
				.query(String.class).list();
		assertThat(visible).containsExactly("DOC-CURRENT");
	}

	@Test
	void adminSeesRestrictedButStillNotExpired() {
		List<String> visible = jdbc.sql(FILTERED_SEARCH)
				.params(Map.of("asOf", java.sql.Date.valueOf("2025-06-01"), "roles", "{admin}", "query", vector(1)))
				.query(String.class).list();
		assertThat(visible).containsExactlyInAnyOrder("DOC-CURRENT", "DOC-RESTRICTED");
	}

	@Test
	void metadataAndFullTextFiltersWork() {
		Integer byMetadata = jdbc.sql("SELECT count(*) FROM knowledge_chunk WHERE metadata @> '{\"section\": \"payment\"}'")
				.query(Integer.class).single();
		Integer byText = jdbc.sql("SELECT count(*) FROM knowledge_chunk WHERE content_tsv @@ plainto_tsquery('english', 'payment terms')")
				.query(Integer.class).single();
		assertThat(byMetadata).isEqualTo(3);
		assertThat(byText).isEqualTo(3);
	}

	@Test
	void multipleVersionsOfADocumentCoexist() {
		insertDocument("DOC-CURRENT", "2", "2025-09-01", null, "{planner,admin}", 3);
		Integer versions = jdbc.sql("SELECT count(*) FROM knowledge_document WHERE document_id = 'DOC-CURRENT'")
				.query(Integer.class).single();
		assertThat(versions).isEqualTo(2);
	}

}
