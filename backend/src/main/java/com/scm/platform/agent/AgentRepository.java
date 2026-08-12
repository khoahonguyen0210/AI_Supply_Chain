package com.scm.platform.agent;

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

@Repository
public class AgentRepository {

	public record ConversationRow(UUID conversationId, String userId, Instant createdAt) {
	}

	public record TaskRow(UUID taskId, UUID conversationId, String engineTaskId, String requestText, String status,
			String answer, JsonNode trace, JsonNode citations, JsonNode assumptions, JsonNode violations,
			String recommendationId, String approvalId, Instant createdAt) {
	}

	private static final String TASK_COLUMNS = "task_id, conversation_id, engine_task_id, request_text, status,"
			+ " answer, trace::text AS trace, citations::text AS citations, assumptions::text AS assumptions,"
			+ " violations::text AS violations, recommendation_id, approval_id, created_at";

	private final JdbcClient jdbc;

	private final JsonMapper json;

	private final RowMapper<TaskRow> taskMapper;

	public AgentRepository(JdbcClient jdbc, JsonMapper json) {
		this.jdbc = jdbc;
		this.json = json;
		this.taskMapper = (rs, i) -> new TaskRow(rs.getObject("task_id", UUID.class),
				rs.getObject("conversation_id", UUID.class), rs.getString("engine_task_id"),
				rs.getString("request_text"), rs.getString("status"), rs.getString("answer"),
				this.json.readTree(rs.getString("trace")), this.json.readTree(rs.getString("citations")),
				this.json.readTree(rs.getString("assumptions")), this.json.readTree(rs.getString("violations")),
				rs.getString("recommendation_id"), rs.getString("approval_id"),
				rs.getObject("created_at", OffsetDateTime.class).toInstant());
	}

	public UUID createConversation(String userId) {
		return jdbc.sql("INSERT INTO agent_conversation (user_id) VALUES (:user) RETURNING conversation_id")
				.param("user", userId).query(UUID.class).single();
	}

	public Optional<ConversationRow> conversation(UUID id) {
		return jdbc.sql("SELECT conversation_id, user_id, created_at FROM agent_conversation"
				+ " WHERE conversation_id = :id").param("id", id)
				.query((rs, i) -> new ConversationRow(rs.getObject(1, UUID.class), rs.getString(2),
						rs.getObject(3, OffsetDateTime.class).toInstant()))
				.optional();
	}

	public List<ConversationRow> conversations(String userId, int limit) {
		return jdbc.sql("SELECT conversation_id, user_id, created_at FROM agent_conversation"
				+ " WHERE user_id = :user ORDER BY created_at DESC LIMIT :limit").param("user", userId)
				.param("limit", limit)
				.query((rs, i) -> new ConversationRow(rs.getObject(1, UUID.class), rs.getString(2),
						rs.getObject(3, OffsetDateTime.class).toInstant()))
				.list();
	}

	public UUID insertTask(UUID conversationId, String userId, String role, String text, JsonNode run) {
		return jdbc.sql("""
				INSERT INTO agent_task (conversation_id, engine_task_id, user_id, user_role, request_text, status, answer,
				    trace, citations, assumptions, violations, recommendation_id, approval_id)
				VALUES (:conversation, :engineTask, :user, :role, :text, :status, :answer, CAST(:trace AS jsonb),
				    CAST(:citations AS jsonb), CAST(:assumptions AS jsonb), CAST(:violations AS jsonb),
				    :recommendation, :approval)
				RETURNING task_id""")
				.param("conversation", conversationId).param("engineTask", run.path("taskId").asString())
				.param("user", userId).param("role", role).param("text", text)
				.param("status", run.path("status").asString()).param("answer", run.path("answer").asString())
				.param("trace", run.path("trace").toString()).param("citations", run.path("citations").toString())
				.param("assumptions", run.path("assumptions").toString())
				.param("violations", run.path("violations").toString())
				.param("recommendation", textOrNull(run.path("recommendationId")))
				.param("approval", textOrNull(run.path("approvalId")))
				.query(UUID.class).single();
	}

	public Optional<TaskRow> task(UUID taskId) {
		return jdbc.sql("SELECT " + TASK_COLUMNS + " FROM agent_task WHERE task_id = :id").param("id", taskId)
				.query(taskMapper).optional();
	}

	public List<TaskRow> tasks(UUID conversationId) {
		return jdbc.sql("SELECT " + TASK_COLUMNS + " FROM agent_task WHERE conversation_id = :id"
				+ " ORDER BY created_at, task_id").param("id", conversationId).query(taskMapper).list();
	}

	public Optional<String> taskOwner(UUID taskId) {
		return jdbc.sql("SELECT user_id FROM agent_task WHERE task_id = :id").param("id", taskId)
				.query(String.class).optional();
	}

	private static String textOrNull(JsonNode node) {
		return node.isNull() || node.isMissingNode() ? null : node.asString();
	}

}
