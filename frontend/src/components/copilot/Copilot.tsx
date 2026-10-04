"use client";

import { useEffect, useRef, useState } from "react";
import type { FormEvent } from "react";
import { Notice, Panel, ResourceView } from "@/components/ui";
import { errorMessage } from "@/lib/api/client";
import { getConversation, listConversations, runAgentTask } from "@/lib/api/decisions";
import type { AgentTask, Conversation } from "@/lib/api/types";
import { formatDateTime } from "@/lib/format";
import { useSession } from "@/lib/session";
import { useResource } from "@/lib/useResource";
import { TaskCard } from "./TaskCard";

export const EXAMPLES = [
  "Demand for SKU-001 is expected to rise by 20%. What should I do?",
  "What is the demand forecast for SKU-002 over the next 4 weeks?",
  "Which suppliers can deliver SKU-003 to W1 and what do they cost?",
  "Who must approve a purchase order above USD 20,000?",
];

export function Copilot() {
  const { user, ready } = useSession();
  const conversations = useResource(ready ? user.userId : null, (signal) => listConversations(signal));
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [tasks, setTasks] = useState<AgentTask[]>([]);
  const [text, setText] = useState("");
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const endRef = useRef<HTMLDivElement>(null);

  // Switching user must not show the previous user's conversation.
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset when the signed-in user changes
    setConversationId(null);
    setTasks([]);
    setError(null);
  }, [user.userId]);

  useEffect(() => {
    endRef.current?.scrollIntoView?.({ behavior: "smooth", block: "end" });
  }, [tasks.length, sending]);

  async function open(conversation: Conversation) {
    setError(null);
    try {
      const view = await getConversation(conversation.conversationId);
      setConversationId(conversation.conversationId);
      setTasks(view.tasks);
    } catch (failure) {
      setError(errorMessage(failure));
    }
  }

  async function send(request: string) {
    const trimmed = request.trim();
    if (!trimmed || sending) return;
    setSending(true);
    setError(null);
    try {
      const task = await runAgentTask(trimmed, conversationId ?? undefined);
      setConversationId(task.conversationId);
      setTasks((current) => [...current, task]);
      setText("");
      conversations.reload();
    } catch (failure) {
      setError(errorMessage(failure));
    } finally {
      setSending(false);
    }
  }

  function submit(event: FormEvent) {
    event.preventDefault();
    void send(text);
  }

  return (
    <div className="stack">
      <div>
        <h1>Assistant</h1>
        <p className="lede">Ask about sales, stock or suppliers. A manager approves every order.</p>
      </div>
      <div className="grid-2" style={{ gridTemplateColumns: "minmax(0, 260px) minmax(0, 1fr)" }}>
        <Panel
          title="Conversations"
          id="conversations"
          actions={
            <button
              type="button"
              onClick={() => {
                setConversationId(null);
                setTasks([]);
              }}
            >
              New
            </button>
          }
        >
          <ResourceView state={conversations.state} onRetry={conversations.reload}>
            {(rows) =>
              rows.length === 0 ? (
                <p className="muted">No conversations yet.</p>
              ) : (
                <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
                  {rows.map((c) => (
                    <li key={c.conversationId}>
                      <button
                        type="button"
                        className="link-button"
                        aria-current={c.conversationId === conversationId ? "true" : undefined}
                        onClick={() => void open(c)}
                      >
                        {formatDateTime(c.createdAt)}
                      </button>
                    </li>
                  ))}
                </ul>
              )
            }
          </ResourceView>
        </Panel>

        <Panel title="Conversation" id="conversation">
          <div className="chat" aria-live="polite">
            {tasks.length === 0 && !sending ? (
              <div className="stack">
                <p className="muted">Examples:</p>
                <div className="row">
                  {EXAMPLES.map((example) => (
                    <button key={example} type="button" onClick={() => void send(example)}>
                      {example}
                    </button>
                  ))}
                </div>
              </div>
            ) : null}
            {tasks.map((task) => (
              <TaskCard key={task.taskId} task={task} />
            ))}
            {sending ? <p role="status">Working on it…</p> : null}
            <div ref={endRef} />
          </div>
          {error ? <Notice tone="bad">{error}</Notice> : null}
          <form className="stack" onSubmit={submit} style={{ marginTop: 12 }}>
            <label className="field">
              <span>Your question</span>
              <textarea
                rows={3}
                value={text}
                maxLength={2000}
                onChange={(e) => setText(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) void send(text);
                }}
              />
            </label>
            <div className="row">
              <button type="submit" className="primary" disabled={sending || text.trim() === ""}>
                {sending ? "Sending…" : "Send"}
              </button>
              <span className="muted">Ctrl+Enter sends</span>
            </div>
          </form>
        </Panel>
      </div>
    </div>
  );
}
