import type { Metadata } from "next";
import {
  generateMatchMetadata,
  renderMatchDetailPage,
} from "./MatchPageContent";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  return generateMatchMetadata(params);
}

export default async function MatchDetailPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  return renderMatchDetailPage(params);
}
