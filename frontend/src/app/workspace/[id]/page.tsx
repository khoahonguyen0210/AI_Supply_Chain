import type { Metadata } from "next";
import { RecommendationDetailView } from "@/components/workspace/RecommendationDetailView";

export const metadata: Metadata = { title: "Recommendation" };

export default async function RecommendationPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <RecommendationDetailView id={decodeURIComponent(id)} />;
}
