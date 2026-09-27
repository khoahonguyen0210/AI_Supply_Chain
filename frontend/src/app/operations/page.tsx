import type { Metadata } from "next";
import { Operations } from "@/components/operations/Operations";

export const metadata: Metadata = { title: "Monitoring" };

export default function OperationsPage() {
  return <Operations />;
}
