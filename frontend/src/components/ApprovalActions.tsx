"use client";

import { useState } from "react";
import { Notice } from "@/components/ui";
import { errorMessage } from "@/lib/api/client";
import { decideApproval } from "@/lib/api/decisions";
import type { ApprovalDetail } from "@/lib/api/types";

/**
 * Approve or reject a pending approval. Who may decide is the planning engine's rule; if it refuses (wrong
 * role, own request, already decided) its reason is shown and nothing changes.
 */
export function ApprovalActions({
  approvalId,
  onDecided,
}: {
  approvalId: string;
  onDecided: (detail: ApprovalDetail) => void;
}) {
  const [rationale, setRationale] = useState("");
  const [busy, setBusy] = useState<"APPROVED" | "REJECTED" | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function decide(outcome: "APPROVED" | "REJECTED") {
    setBusy(outcome);
    setError(null);
    try {
      onDecided(await decideApproval(approvalId, outcome, rationale.trim()));
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="stack">
      <label className="field">
        <span>Rationale (optional)</span>
        <input
          value={rationale}
          maxLength={500}
          onChange={(e) => setRationale(e.target.value)}
          placeholder="Why you are approving or rejecting"
        />
      </label>
      <div className="row">
        <button type="button" className="primary" disabled={busy !== null} onClick={() => decide("APPROVED")}>
          {busy === "APPROVED" ? "Approving…" : "Approve"}
        </button>
        <button type="button" className="danger" disabled={busy !== null} onClick={() => decide("REJECTED")}>
          {busy === "REJECTED" ? "Rejecting…" : "Reject"}
        </button>
      </div>
      {error ? <Notice tone="bad">{error}</Notice> : null}
    </div>
  );
}
