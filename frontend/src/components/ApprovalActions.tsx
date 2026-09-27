"use client";

import { useState } from "react";
import { Notice } from "@/components/ui";
import { errorMessage } from "@/lib/api/client";
import { decideApproval } from "@/lib/api/decisions";
import type { ApprovalDetail } from "@/lib/api/types";

/** The engine decides who may approve; its refusal reason is shown. */
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
        <span>Reason (optional)</span>
        <input
          value={rationale}
          maxLength={500}
          onChange={(e) => setRationale(e.target.value)}
          placeholder="Why you approve or reject this order"
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
