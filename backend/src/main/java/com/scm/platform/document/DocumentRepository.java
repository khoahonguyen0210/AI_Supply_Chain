package com.scm.platform.document;

import java.time.LocalDate;
import java.util.List;
import java.util.Optional;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;

/** Role filtering runs in SQL, so an unreadable document never leaves the database. */
@Repository
public class DocumentRepository {

	public record DocumentSummary(String documentId, String version, String docType, String title,
			LocalDate effectiveDate, LocalDate expiryDate, String supplierId, boolean inForce) {
	}

	public record DocumentDetail(DocumentSummary summary, List<String> allowedRoles, String content) {
	}

	private static final String SUMMARY_COLUMNS = "document_id, version, doc_type, title, effective_date, expiry_date,"
			+ " supplier_id, (effective_date <= :asOf AND (expiry_date IS NULL OR expiry_date >= :asOf)) AS in_force";

	private final JdbcClient jdbc;

	public DocumentRepository(JdbcClient jdbc) {
		this.jdbc = jdbc;
	}

	public List<DocumentSummary> list(String role, LocalDate asOf, String docType, String supplierId,
			boolean includeSuperseded) {
		return jdbc.sql("SELECT " + SUMMARY_COLUMNS + """
				 FROM knowledge_document
				WHERE :role = ANY (allowed_roles)
				  AND (CAST(:type AS text) IS NULL OR doc_type = :type)
				  AND (CAST(:supplier AS text) IS NULL OR supplier_id = :supplier)
				  AND (:all OR (effective_date <= :asOf AND (expiry_date IS NULL OR expiry_date >= :asOf)))
				ORDER BY document_id, effective_date DESC""")
				.param("role", role).param("asOf", asOf).param("type", docType).param("supplier", supplierId)
				.param("all", includeSuperseded)
				.query((rs, i) -> summary(rs)).list();
	}

	public Optional<DocumentDetail> find(String role, String documentId, String version, LocalDate asOf) {
		return jdbc.sql("SELECT " + SUMMARY_COLUMNS + """
				, allowed_roles, content FROM knowledge_document
				WHERE document_id = :id AND :role = ANY (allowed_roles)
				  AND (CAST(:version AS text) IS NULL OR version = :version)
				ORDER BY (effective_date <= :asOf AND (expiry_date IS NULL OR expiry_date >= :asOf)) DESC,
				         effective_date DESC
				LIMIT 1""")
				.param("id", documentId).param("role", role).param("version", version).param("asOf", asOf)
				.query((rs, i) -> new DocumentDetail(summary(rs), List.of((String[]) rs.getArray("allowed_roles").getArray()),
						rs.getString("content")))
				.optional();
	}

	private static DocumentSummary summary(java.sql.ResultSet rs) throws java.sql.SQLException {
		return new DocumentSummary(rs.getString("document_id"), rs.getString("version"), rs.getString("doc_type"),
				rs.getString("title"), rs.getObject("effective_date", LocalDate.class),
				rs.getObject("expiry_date", LocalDate.class), rs.getString("supplier_id"), rs.getBoolean("in_force"));
	}

}
