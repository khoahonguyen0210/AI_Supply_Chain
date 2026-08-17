import type { Metadata } from "next";
import { Suspense } from "react";
import { Approvals } from "@/components/approvals/Approvals";

export const metadata: Metadata = { title: "Approvals" };

export default function ApprovalsPage() {
  return (
    <Suspense fallback={<p role="status">Loading…</p>}>
      <Approvals />
    </Suspense>
  );
}
