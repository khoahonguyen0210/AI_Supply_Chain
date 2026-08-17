import Link from "next/link";
import type { PolicyCitation } from "@/lib/api/types";

export function Citations({ citations }: { citations: PolicyCitation[] }) {
  if (citations.length === 0) return <p className="muted">No documents were cited.</p>;
  return (
    <div>
      {citations.map((c) => (
        <blockquote
          className="citation"
          key={`${c.documentId}-${c.version}-${c.excerpt.slice(0, 24)}`}
        >
          <Link href={`/documents?open=${encodeURIComponent(c.documentId)}&version=${encodeURIComponent(c.version)}`}>
            {c.documentId} · {c.version}
          </Link>
          {c.status && c.status !== "CURRENT" ? <span className="muted"> ({c.status.toLowerCase()})</span> : null}
          <div>{c.excerpt}</div>
        </blockquote>
      ))}
    </div>
  );
}
