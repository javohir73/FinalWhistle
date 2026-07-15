import type { Metadata } from "next";
import { notFound } from "next/navigation";
import { getNrlMatchesServer } from "@/lib/api";
import { MatchesClient } from "./MatchesClient";

export const revalidate = 300;

export const metadata: Metadata = {
  title: "NRL fixtures — FinalWhistle",
  description:
    "Every NRL fixture with the model's frozen win probabilities, filterable by upcoming, live, or finished.",
};

export default async function NrlMatchesPage() {
  const fixtures = await getNrlMatchesServer().catch(() => null);
  if (!fixtures) notFound();
  return <MatchesClient initial={fixtures} />;
}
