import type { Metadata } from "next";
import { Workspace } from "@/components/workspace/Workspace";

export const metadata: Metadata = { title: "Decision workspace" };

export default function WorkspacePage() {
  return <Workspace />;
}
