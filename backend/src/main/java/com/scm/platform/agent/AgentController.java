package com.scm.platform.agent;

import com.scm.platform.agent.AgentRepository.ConversationRow;
import com.scm.platform.agent.AgentRepository.TaskRow;
import com.scm.platform.approval.ApprovalService;
import com.scm.platform.error.ApiException;
import com.scm.platform.mlservice.MlEngineClient;
import com.scm.platform.security.Actor;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotBlank;
import jakarta.validation.constraints.Size;
import java.util.List;
import java.util.UUID;
import org.springframework.http.HttpStatus;
import org.springframework.http.ResponseEntity;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;
import tools.jackson.databind.JsonNode;

@RestController
@RequestMapping("/api/agent")
public class AgentController {

	private final MlEngineClient engine;

	private final AgentRepository repository;

	private final ApprovalService approvals;

	private final TransactionTemplate transaction;

	public AgentController(MlEngineClient engine, AgentRepository repository, ApprovalService approvals,
			PlatformTransactionManager transactionManager) {
		this.engine = engine;
		this.repository = repository;
		this.approvals = approvals;
		this.transaction = new TransactionTemplate(transactionManager);
	}

	public record TaskRequest(@NotBlank @Size(max = 2000) String text, UUID conversationId) {
	}

	public record ConversationView(ConversationRow conversation, List<TaskRow> tasks) {
	}

	@PostMapping("/tasks")
	public ResponseEntity<TaskRow> run(Actor actor, @Valid @RequestBody TaskRequest request) {
		UUID conversationId = request.conversationId() == null ? null : ownConversation(actor, request.conversationId());
		JsonNode run = engine.runAgentTask(actor, request.text());
		JsonNode approvalId = run.path("approvalId");
		JsonNode approval = approvalId.isString() ? engine.getApproval(approvalId.asString()) : null;
		TaskRow task = transaction.execute(status -> {
			if (approval != null) {
				approvals.mirror(approval);
			}
			UUID conversation = conversationId != null ? conversationId : repository.createConversation(actor.userId());
			UUID taskId = repository.insertTask(conversation, actor.userId(), actor.role(), request.text(), run);
			return repository.task(taskId).orElseThrow();
		});
		return ResponseEntity.status(HttpStatus.CREATED).header("Location", "/api/agent/tasks/" + task.taskId())
				.body(task);
	}

	@GetMapping("/tasks/{taskId}")
	public TaskRow task(Actor actor, @PathVariable UUID taskId) {
		String owner = repository.taskOwner(taskId).orElse(null);
		if (owner == null || !owner.equals(actor.userId())) {
			throw ApiException.notFound("UNKNOWN_TASK", "no task " + taskId);
		}
		return repository.task(taskId).orElseThrow();
	}

	@GetMapping("/conversations")
	public List<ConversationRow> conversations(Actor actor, @RequestParam(defaultValue = "20") int limit) {
		return repository.conversations(actor.userId(), Math.max(1, Math.min(limit, 100)));
	}

	@GetMapping("/conversations/{conversationId}")
	public ConversationView conversation(Actor actor, @PathVariable UUID conversationId) {
		ownConversation(actor, conversationId);
		return new ConversationView(repository.conversation(conversationId).orElseThrow(),
				repository.tasks(conversationId));
	}

	/** A conversation is private to its creator; others get the same 404 as for a missing one. */
	private UUID ownConversation(Actor actor, UUID conversationId) {
		return repository.conversation(conversationId).filter(c -> c.userId().equals(actor.userId()))
				.map(ConversationRow::conversationId)
				.orElseThrow(() -> ApiException.notFound("UNKNOWN_CONVERSATION", "no conversation " + conversationId));
	}

}
