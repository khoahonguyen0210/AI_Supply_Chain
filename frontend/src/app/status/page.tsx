import type { Metadata } from "next";
import { ConnectionStatus } from "@/components/ConnectionStatus";

export const metadata: Metadata = { title: "System status" };

export default function StatusPage() {
  return (
    <section>
      <h1>System status</h1>
      <p>Live connectivity check against the Spring backend.</p>
      <ConnectionStatus />
    </section>
  );
}
