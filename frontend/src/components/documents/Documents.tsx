"use client";

import { useSearchParams } from "next/navigation";
import { useState } from "react";
import { Badge, EmptyState, Panel, ResourceView } from "@/components/ui";
import { getDocument, listDocuments } from "@/lib/api/decisions";
import { formatDate, humanize } from "@/lib/format";
import { useSession } from "@/lib/session";
import { useResource } from "@/lib/useResource";

const TYPES = ["CONTRACT", "SLA", "POLICY", "SOP", "CERTIFICATION", "SPECIFICATION", "SHIPPING_TERMS"];

function DocumentText({ documentId, version }: { documentId: string; version: string }) {
  const { user, ready } = useSession();
  const { state, reload } = useResource(ready ? `${user.userId}:${documentId}:${version}` : null, (signal) =>
    getDocument(documentId, { version }, signal),
  );
  return (
    <ResourceView state={state} onRetry={reload} loadingLabel="Loading document…">
      {(doc) => (
        <div className="stack">
          <p className="muted" style={{ margin: 0 }}>
            {humanize(doc.summary.docType)} · effective {formatDate(doc.summary.effectiveDate)}
            {doc.summary.expiryDate ? ` to ${formatDate(doc.summary.expiryDate)}` : ""} · readable by{" "}
            {doc.allowedRoles.map(humanize).join(", ")}
          </p>
          <pre style={{ whiteSpace: "pre-wrap", margin: 0, fontFamily: "inherit" }}>{doc.content}</pre>
        </div>
      )}
    </ResourceView>
  );
}

/** The contracts, SLAs, policies and SOPs the signed-in role is allowed to read. */
export function Documents() {
  const { user, ready } = useSession();
  const params = useSearchParams();
  const [docType, setDocType] = useState("");
  const [includeSuperseded, setIncludeSuperseded] = useState(params.get("version") !== null);
  const [open, setOpen] = useState<{ id: string; version: string } | null>(
    params.get("open") ? { id: params.get("open")!, version: params.get("version") ?? "" } : null,
  );
  const { state, reload } = useResource(
    ready ? `${user.userId}:${docType}:${includeSuperseded}` : null,
    (signal) => listDocuments({ docType: docType || undefined, includeSuperseded }, signal),
  );

  return (
    <div className="stack">
      <div>
        <h1>Documents</h1>
        <p className="lede">
          Only documents your role may read are listed. Superseded versions are hidden unless you ask for
          them.
        </p>
      </div>
      <div className="grid-2" style={{ gridTemplateColumns: "minmax(0, 1fr) minmax(0, 1.4fr)" }}>
        <Panel
          title="Library"
          id="library"
          actions={
            <>
              <label className="row">
                <span className="muted">Type</span>
                <select value={docType} onChange={(e) => setDocType(e.target.value)}>
                  <option value="">All</option>
                  {TYPES.map((t) => (
                    <option key={t} value={t}>
                      {humanize(t)}
                    </option>
                  ))}
                </select>
              </label>
              <label className="row">
                <input
                  type="checkbox"
                  checked={includeSuperseded}
                  onChange={(e) => setIncludeSuperseded(e.target.checked)}
                />
                <span>Include superseded</span>
              </label>
            </>
          }
        >
          <ResourceView state={state} onRetry={reload}>
            {(rows) =>
              rows.length === 0 ? (
                <EmptyState>No documents are available to your role.</EmptyState>
              ) : (
                <ul className="stack" style={{ listStyle: "none", padding: 0, margin: 0 }}>
                  {rows.map((d) => (
                    <li key={`${d.documentId}-${d.version}`}>
                      <button
                        type="button"
                        className="link-button"
                        onClick={() => setOpen({ id: d.documentId, version: d.version })}
                      >
                        {d.title}
                      </button>{" "}
                      <span className="muted">
                        {d.documentId} · {d.version}
                      </span>{" "}
                      {d.inForce ? <Badge tone="good">in force</Badge> : <Badge tone="neutral">superseded</Badge>}
                    </li>
                  ))}
                </ul>
              )
            }
          </ResourceView>
        </Panel>
        <Panel title={open ? `${open.id}${open.version ? ` · ${open.version}` : ""}` : "Document"} id="document">
          {open ? (
            <DocumentText key={`${open.id}-${open.version}`} documentId={open.id} version={open.version} />
          ) : (
            <EmptyState>Choose a document to read it.</EmptyState>
          )}
        </Panel>
      </div>
    </div>
  );
}
