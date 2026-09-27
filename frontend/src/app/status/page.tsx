import type { Metadata } from "next";
import { ConnectionStatus } from "@/components/ConnectionStatus";

export const metadata: Metadata = { title: "Status" };

export default function StatusPage() {
  return (
    <section>
      <h1>Status</h1>
      <p>Live connectivity check against the Spring backend.</p>
      <ConnectionStatus />
    </section>
  );
}
