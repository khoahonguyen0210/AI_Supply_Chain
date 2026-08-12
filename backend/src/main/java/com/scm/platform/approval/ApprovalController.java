package com.scm.platform.approval;

import com.scm.platform.approval.ApprovalRepository.ApprovalRow;
import com.scm.platform.approval.ApprovalRepository.DecisionRow;
import com.scm.platform.approval.ApprovalRepository.LineRow;
import com.scm.platform.approval.ApprovalRepository.RecommendationRow;
import com.scm.platform.error.ApiException;
import com.scm.platform.security.Actor;
import jakarta.validation.Valid;
import jakarta.validation.constraints.NotNull;
import jakarta.validation.constraints.Size;
import java.util.List;
import org.springframework.web.bind.annotation.GetMapping;
import org.springframework.web.bind.annotation.PathVariable;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;
import org.springframework.web.bind.annotation.RequestMapping;
import org.springframework.web.bind.annotation.RequestParam;
import org.springframework.web.bind.annotation.RestController;

/** Who may decide is the engine's rule, not Java's. */
@RestController
@RequestMapping("/api")
public class ApprovalController {

	private static final List<String> APPROVAL_STATUSES = List.of("PENDING", "APPROVED", "REJECTED");

	private static final List<String> RECOMMENDATION_STATUSES = List.of("PROPOSED", "PENDING_APPROVAL", "APPROVED",
			"REJECTED");

	private final ApprovalService approvals;

	private final ApprovalRepository repository;

	public ApprovalController(ApprovalService approvals, ApprovalRepository repository) {
		this.approvals = approvals;
		this.repository = repository;
	}

	public record DecisionRequest(@NotNull Outcome outcome, @Size(max = 500) String rationale) {
	}

	public enum Outcome {
		APPROVED, REJECTED
	}

	public record ApprovalDetail(ApprovalRow approval, RecommendationDetail recommendation,
			List<DecisionRow> decisions) {
	}

	public record RecommendationDetail(RecommendationRow recommendation, List<LineRow> lines, ApprovalRow approval,
			List<DecisionRow> decisions) {
	}

	@GetMapping("/approvals")
	public List<ApprovalRow> list(Actor actor, @RequestParam(required = false) String status) {
		return repository.approvals(checked(status, APPROVAL_STATUSES));
	}

	@GetMapping("/approvals/{approvalId}")
	public ApprovalDetail get(Actor actor, @PathVariable String approvalId) {
		ApprovalRow approval = approvals.get(approvalId);
		return new ApprovalDetail(approval, recommendation(approval.recommendationId()),
				repository.decisions(approvalId));
	}

	@PostMapping("/approvals/{approvalId}/decision")
	public ApprovalDetail decide(Actor actor, @PathVariable String approvalId,
			@Valid @RequestBody DecisionRequest request) {
		approvals.decide(actor, approvalId, request.outcome().name(), request.rationale());
		return get(actor, approvalId);
	}

	@GetMapping("/recommendations")
	public List<RecommendationRow> recommendations(Actor actor, @RequestParam(required = false) String status) {
		return repository.recommendations(checked(status, RECOMMENDATION_STATUSES));
	}

	@GetMapping("/recommendations/{recommendationId}")
	public RecommendationDetail recommendation(Actor actor, @PathVariable String recommendationId) {
		return recommendation(recommendationId);
	}

	private RecommendationDetail recommendation(String recommendationId) {
		RecommendationRow row = repository.recommendation(recommendationId).orElseThrow(
				() -> ApiException.notFound("UNKNOWN_RECOMMENDATION", "no recommendation " + recommendationId));
		ApprovalRow approval = repository.approvalForRecommendation(recommendationId).orElse(null);
		return new RecommendationDetail(row, repository.lines(recommendationId), approval,
				approval == null ? List.of() : repository.decisions(approval.approvalId()));
	}

	private static String checked(String status, List<String> allowed) {
		if (status != null && !allowed.contains(status)) {
			throw ApiException.badRequest("INVALID_STATUS", "status must be one of " + allowed);
		}
		return status;
	}

}
