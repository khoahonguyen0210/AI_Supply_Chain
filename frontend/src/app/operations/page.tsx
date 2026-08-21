import type { Metadata } from "next";
import { Operations } from "@/components/operations/Operations";

export const metadata: Metadata = { title: "Operations" };

export default function OperationsPage() {
  return <Operations />;
}
