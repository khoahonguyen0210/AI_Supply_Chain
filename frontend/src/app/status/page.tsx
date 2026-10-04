import type { Metadata } from "next";
import { ConnectionStatus } from "@/components/ConnectionStatus";

export const metadata: Metadata = { title: "Status" };

export default function StatusPage() {
  return (
    <div className="stack">
      <div>
        <h1>Status</h1>
        <p className="lede">Checks that the app can reach its server.</p>
      </div>
      <ConnectionStatus />
    </div>
  );
}
