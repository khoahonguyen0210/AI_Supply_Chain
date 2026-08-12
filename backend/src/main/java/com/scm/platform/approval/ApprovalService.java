package com.scm.platform.approval;

import com.scm.platform.approval.ApprovalRepository.ApprovalRow;
import com.scm.platform.error.ApiException;
import com.scm.platform.mlservice.MlEngineClient;
import com.scm.platform.security.Actor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;

/**
 * The approval workflow around the engine's rules. The engine decides who may approve and when an
 * approval is complete; this service relays the decision, stores what the engine returned and, once an
 * approval is complete, creates the approved purchase orders.
 */
@Service
public class ApprovalService {

	private final MlEngineClient engine;

	private final ApprovalRepository repository;

	private final TransactionTemplate transaction;

	public ApprovalService(MlEngineClient engine, ApprovalRepository repository,
			PlatformTransactionManager transactionManager) {
		this.engine = engine;
		this.repository = repository;
		this.transaction = new TransactionTemplate(transactionManager);
	}

	/** Stores an engine approval record and its recommendation; safe to repeat. */
	@Transactional
	public void mirror(JsonNode approval) {
		repository.upsertRecommendation(approval.path("recommendation"));
		repository.upsertApproval(approval);
	}

	/**
	 * Relays a human decision. An engine refusal (not authorized, already decided, self-approval) is
	 * returned to the caller unchanged and nothing is stored.
	 */
	public ApprovalRow decide(Actor approver, String approvalId, String outcome, String rationale) {
		JsonNode record = engine.decideApproval(approver, approvalId, outcome, rationale);
		return transaction.execute(status -> store(approver, approvalId, outcome, rationale, record));
	}

	private ApprovalRow store(Actor approver, String approvalId, String outcome, String rationale,
			JsonNode record) {
		repository.upsertRecommendation(record.path("recommendation"));
		repository.upsertApproval(record);
		String recommendationId = record.path("recommendation").path("recommendationId").asString();
		repository.appendDecision(approvalId, recommendationId, approver.userId(), approver.role(), outcome,
				rationale);
		if ("APPROVED".equals(record.path("status").asString())) {
			repository.createPurchaseOrders(approvalId, recommendationId);
		}
		return repository.approval(approvalId).orElseThrow();
	}

	public ApprovalRow get(String approvalId) {
		return repository.approval(approvalId)
				.orElseThrow(() -> ApiException.notFound("UNKNOWN_APPROVAL", "no approval " + approvalId));
	}

}
