import type { Metadata } from "next";
import { Suspense } from "react";
import { Documents } from "@/components/documents/Documents";

export const metadata: Metadata = { title: "Documents" };

export default function DocumentsPage() {
  return (
    <Suspense fallback={<p role="status">Loading…</p>}>
      <Documents />
    </Suspense>
  );
}
