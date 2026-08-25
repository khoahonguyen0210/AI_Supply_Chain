package com.scm.platform.audit;

import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.List;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Service;

/**
 * The audit trail: who did what, from where, and how it ended. Entries are append-only (a database trigger
 * forbids update and delete). A failure to write an entry is logged loudly but does not fail the request:
 * refusing every action whenever the audit table has a problem would be an outage caused by the safeguard.
 */
@Service
public class AuditService {

	public enum Outcome {
		SUCCESS, DENIED, FAILED, LIMITED
	}

	public record Entry(long auditId, Instant at, String actorUser, String actorRole, String action, String resource,
			Outcome outcome, Integer status, String clientIp, String detail) {
	}

	private static final Logger log = LoggerFactory.getLogger(AuditService.class);

	private static final int MAX_TEXT = 500;

	private final JdbcClient jdbc;

	public AuditService(JdbcClient jdbc) {
		this.jdbc = jdbc;
	}

	public void record(String actorUser, String actorRole, String action, String resource, Outcome outcome,
			Integer status, String clientIp, String detail) {
		try {
			jdbc.sql("""
					INSERT INTO audit_log (actor_user, actor_role, action, resource, outcome, status, client_ip, detail)
					VALUES (:user, :role, :action, :resource, :outcome, :status, :ip, :detail)""")
					.param("user", actorUser).param("role", actorRole).param("action", truncate(action))
					.param("resource", truncate(resource)).param("outcome", outcome.name()).param("status", status)
					.param("ip", clientIp).param("detail", truncate(detail)).update();
		}
		catch (RuntimeException ex) {
			log.error("could not write audit entry {} {} by {}", action, outcome, actorUser, ex);
		}
	}

	/** The most recent entries, newest first, optionally for one user or one outcome. */
	public List<Entry> recent(String actorUser, Outcome outcome, int limit) {
		return jdbc.sql("""
				SELECT audit_id, at, actor_user, actor_role, action, resource, outcome, status, client_ip, detail
				FROM audit_log
				WHERE (CAST(:user AS text) IS NULL OR actor_user = :user)
				  AND (CAST(:outcome AS text) IS NULL OR outcome = :outcome)
				ORDER BY audit_id DESC LIMIT :limit""")
				.param("user", actorUser).param("outcome", outcome == null ? null : outcome.name())
				.param("limit", Math.max(1, Math.min(limit, 500)))
				.query((rs, i) -> new Entry(rs.getLong(1), rs.getObject(2, OffsetDateTime.class).toInstant(),
						rs.getString(3), rs.getString(4), rs.getString(5), rs.getString(6),
						Outcome.valueOf(rs.getString(7)), (Integer) rs.getObject(8), rs.getString(9),
						rs.getString(10)))
				.list();
	}

	private static String truncate(String text) {
		return text == null || text.length() <= MAX_TEXT ? text : text.substring(0, MAX_TEXT);
	}

}
