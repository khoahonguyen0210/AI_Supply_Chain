import type { Metadata } from "next";
import { Copilot } from "@/components/copilot/Copilot";

export const metadata: Metadata = { title: "Assistant" };

export default function CopilotPage() {
  return <Copilot />;
}
