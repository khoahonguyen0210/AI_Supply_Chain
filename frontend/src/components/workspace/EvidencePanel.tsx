"use client";

import { useState } from "react";
import type { FormEvent } from "react";
import { Citations } from "@/components/Citations";
import { Notice, Panel, StatusBadge } from "@/components/ui";
import { errorMessage } from "@/lib/api/client";
import { askDocuments } from "@/lib/api/decisions";
import type { DocumentAnswer } from "@/lib/api/types";

type Ask =
  | { phase: "idle" }
  | { phase: "loading" }
  | { phase: "error"; message: string }
  | { phase: "done"; answer: DocumentAnswer };

/** Ask the contracts, SLAs and policies a question; the answer is cited or says why it is not given. */
export function EvidencePanel() {
  const [question, setQuestion] = useState("");
  const [ask, setAsk] = useState<Ask>({ phase: "idle" });
  const valid = question.trim().length >= 3;

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!valid) return;
    setAsk({ phase: "loading" });
    try {
      setAsk({ phase: "done", answer: await askDocuments(question.trim()) });
    } catch (error) {
      setAsk({ phase: "error", message: errorMessage(error) });
    }
  }

  return (
    <Panel title="Evidence from contracts and policies" id="evidence">
      <form className="form-row" onSubmit={submit}>
        <label className="field" style={{ flex: "1 1 320px" }}>
          <span>Question</span>
          <input
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Who must approve a purchase order above USD 20,000?"
            maxLength={500}
          />
        </label>
        <button type="submit" className="primary" disabled={!valid || ask.phase === "loading"}>
          {ask.phase === "loading" ? "Searching…" : "Ask"}
        </button>
      </form>
      {ask.phase === "error" ? <Notice tone="bad">{ask.message}</Notice> : null}
      {ask.phase === "done" ? (
        <div className="stack" style={{ marginTop: 12 }}>
          <div className="row">
            <StatusBadge status={ask.answer.status} />
            <span className="muted">answers use only documents your role may read</span>
          </div>
          <p style={{ whiteSpace: "pre-wrap", margin: 0 }}>{ask.answer.answer}</p>
          <Citations citations={ask.answer.citations} />
        </div>
      ) : null}
    </Panel>
  );
}
