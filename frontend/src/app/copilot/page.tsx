import type { Metadata } from "next";
import { Copilot } from "@/components/copilot/Copilot";

export const metadata: Metadata = { title: "Copilot" };

export default function CopilotPage() {
  return <Copilot />;
}
