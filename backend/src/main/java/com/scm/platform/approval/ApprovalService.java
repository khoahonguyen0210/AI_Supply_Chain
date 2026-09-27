package com.scm.platform.approval;

import com.scm.platform.approval.ApprovalRepository.ApprovalRow;
import com.scm.platform.error.ApiException;
import com.scm.platform.mlservice.MlEngineClient;
import com.scm.platform.outcome.OutcomeService;
import com.scm.platform.security.Actor;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;
import tools.jackson.databind.JsonNode;

@Service
public class ApprovalService {

	private final MlEngineClient engine;

	private final ApprovalRepository repository;

	private final TransactionTemplate transaction;

	private final OutcomeService outcomes;

	public ApprovalService(MlEngineClient engine, ApprovalRepository repository,
			PlatformTransactionManager transactionManager, OutcomeService outcomes) {
		this.engine = engine;
		this.repository = repository;
		this.transaction = new TransactionTemplate(transactionManager);
		this.outcomes = outcomes;
	}

	@Transactional
	public void mirror(JsonNode approval) {
		repository.upsertRecommendation(approval.path("recommendation"));
		repository.upsertApproval(approval);
	}

	/** An engine refusal is returned unchanged and nothing is stored. */
	public ApprovalRow decide(Actor approver, String approvalId, String outcome, String rationale) {
		JsonNode record = engine.decideApproval(approver, approvalId, outcome, rationale);
		ApprovalRow stored = transaction.execute(status -> store(approver, approvalId, outcome, rationale, record));
		if (stored != null && "APPROVED".equals(stored.status())) {
			// What the decision relied on, for the feedback loop. Best effort: the approval itself is done.
			outcomes.captureForecastQuietly(approver, stored.recommendationId());
		}
		return stored;
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
