import type { Metadata } from "next";
import {
  generateTeamMetadata,
  renderTeamPage,
} from "./TeamPageContent";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ id: string }>;
}): Promise<Metadata> {
  return generateTeamMetadata(params);
}

export default async function TeamPage({
  params,
}: {
  params: Promise<{ id: string }>;
}) {
  return renderTeamPage(params);
}
