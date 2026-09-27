package com.scm.platform.job;

import java.sql.ResultSet;
import java.sql.SQLException;
import java.time.Duration;
import java.time.Instant;
import java.time.OffsetDateTime;
import java.util.List;
import java.util.Optional;
import java.util.UUID;
import org.springframework.jdbc.core.RowMapper;
import org.springframework.jdbc.core.simple.JdbcClient;
import org.springframework.stereotype.Repository;
import tools.jackson.databind.JsonNode;
import tools.jackson.databind.json.JsonMapper;

/** Worker updates are fenced by locked_by, so a lost lease can't overwrite. */
@Repository
public class JobRepository {

	private static final String COLUMNS = "job_id, job_type, idempotency_key, request_hash, payload::text AS payload,"
			+ " submitted_by, submitted_role, status, attempts, max_attempts, run_after, result::text AS result,"
			+ " error_code, error_message, last_error, created_at, updated_at, started_at, finished_at";

	private final JdbcClient jdbc;

	private final JsonMapper json;

	private final RowMapper<Job> mapper;

	public JobRepository(JdbcClient jdbc, JsonMapper json) {
		this.jdbc = jdbc;
		this.json = json;
		this.mapper = this::mapRow;
	}

	/** Empty when the (type, idempotency key) pair already exists. */
	public Optional<Job> insertIfAbsent(JobType type, String key, String requestHash, JsonNode payload,
			String submittedBy, String submittedRole, int maxAttempts) {
		return jdbc.sql("""
				INSERT INTO job (job_type, idempotency_key, request_hash, payload, submitted_by, submitted_role,
				                 max_attempts)
				VALUES (:type, :key, :hash, CAST(:payload AS jsonb), :by, :role, :max)
				ON CONFLICT (job_type, idempotency_key) DO NOTHING
				RETURNING\s""" + COLUMNS)
				.param("type", type.name())
				.param("key", key)
				.param("hash", requestHash)
				.param("payload", payload.toString())
				.param("by", submittedBy)
				.param("role", submittedRole)
				.param("max", maxAttempts)
				.query(mapper).optional();
	}

	public Optional<Job> findByKey(JobType type, String key) {
		return jdbc.sql("SELECT " + COLUMNS + " FROM job WHERE job_type = :type AND idempotency_key = :key")
				.param("type", type.name()).param("key", key).query(mapper).optional();
	}

	public Optional<Job> find(UUID id) {
		return jdbc.sql("SELECT " + COLUMNS + " FROM job WHERE job_id = :id").param("id", id)
				.query(mapper).optional();
	}

	public java.util.Map<JobStatus, Long> countsByStatus() {
		java.util.Map<JobStatus, Long> counts = new java.util.EnumMap<>(JobStatus.class);
		for (JobStatus status : JobStatus.values()) {
			counts.put(status, 0L);
		}
		jdbc.sql("SELECT status, count(*) FROM job GROUP BY status").query((rs, i) -> {
			counts.put(JobStatus.valueOf(rs.getString(1)), rs.getLong(2));
			return null;
		}).list();
		return counts;
	}

	public double oldestQueuedAgeSeconds() {
		return jdbc.sql("""
				SELECT COALESCE(EXTRACT(EPOCH FROM now() - min(run_after)), 0)
				FROM job WHERE status = 'QUEUED' AND run_after <= now()""")
				.query(Double.class).single();
	}

	public List<Job> recentBy(String submittedBy, int limit) {
		return jdbc.sql("SELECT " + COLUMNS + " FROM job WHERE submitted_by = :by ORDER BY created_at DESC LIMIT :limit")
				.param("by", submittedBy).param("limit", limit).query(mapper).list();
	}

	public Optional<Job> claim(String workerId, Duration lease) {
		jdbc.sql("""
				UPDATE job SET status = 'FAILED', error_code = 'LEASE_EXPIRED',
				    error_message = 'the worker stopped before finishing and no attempts are left',
				    locked_by = NULL, locked_until = NULL, finished_at = now(), updated_at = now()
				WHERE status = 'RUNNING' AND locked_until < now() AND attempts >= max_attempts""").update();
		return jdbc.sql("""
				UPDATE job SET status = 'RUNNING', attempts = attempts + 1, locked_by = :worker,
				    locked_until = now() + make_interval(secs => :lease), started_at = COALESCE(started_at, now()),
				    updated_at = now()
				WHERE job_id = (
				    SELECT job_id FROM job
				    WHERE (status = 'QUEUED' AND run_after <= now()) OR (status = 'RUNNING' AND locked_until < now())
				    ORDER BY run_after, created_at
				    FOR UPDATE SKIP LOCKED
				    LIMIT 1)
				RETURNING\s""" + COLUMNS)
				.param("worker", workerId)
				.param("lease", lease.toMillis() / 1000.0)
				.query(mapper).optional();
	}

	/** False when the worker no longer owns the job. */
	public boolean succeed(UUID id, String workerId, JsonNode result) {
		return jdbc.sql("""
				UPDATE job SET status = 'SUCCEEDED', result = CAST(:result AS jsonb), last_error = NULL,
				    locked_by = NULL, locked_until = NULL, finished_at = now(), updated_at = now()
				WHERE job_id = :id AND status = 'RUNNING' AND locked_by = :worker""")
				.param("result", result.toString()).param("id", id).param("worker", workerId).update() == 1;
	}

	public boolean fail(UUID id, String workerId, String code, String message) {
		return jdbc.sql("""
				UPDATE job SET status = 'FAILED', error_code = :code, error_message = :message,
				    locked_by = NULL, locked_until = NULL, finished_at = now(), updated_at = now()
				WHERE job_id = :id AND status = 'RUNNING' AND locked_by = :worker""")
				.param("code", code).param("message", message).param("id", id).param("worker", workerId)
				.update() == 1;
	}

	public boolean requeue(UUID id, String workerId, String lastError, Duration delay) {
		return jdbc.sql("""
				UPDATE job SET status = 'QUEUED', last_error = :error, run_after = now() + make_interval(secs => :delay),
				    locked_by = NULL, locked_until = NULL, updated_at = now()
				WHERE job_id = :id AND status = 'RUNNING' AND locked_by = :worker""")
				.param("error", lastError).param("delay", delay.toMillis() / 1000.0).param("id", id)
				.param("worker", workerId).update() == 1;
	}

	private Job mapRow(ResultSet rs, int rowNum) throws SQLException {
		return new Job(
				rs.getObject("job_id", UUID.class),
				JobType.valueOf(rs.getString("job_type")),
				rs.getString("idempotency_key"),
				rs.getString("request_hash"),
				json.readTree(rs.getString("payload")),
				rs.getString("submitted_by"),
				rs.getString("submitted_role"),
				JobStatus.valueOf(rs.getString("status")),
				rs.getInt("attempts"),
				rs.getInt("max_attempts"),
				instant(rs, "run_after"),
				rs.getString("result") == null ? null : json.readTree(rs.getString("result")),
				rs.getString("error_code"),
				rs.getString("error_message"),
				rs.getString("last_error"),
				instant(rs, "created_at"),
				instant(rs, "updated_at"),
				instant(rs, "started_at"),
				instant(rs, "finished_at"));
	}

	private static Instant instant(ResultSet rs, String column) throws SQLException {
		OffsetDateTime value = rs.getObject(column, OffsetDateTime.class);
		return value == null ? null : value.toInstant();
	}

}
