import { notFound } from "next/navigation";
import { isWiredCompetition } from "@/lib/sports";
import LegacyGroupsPage from "@/app/groups/page";

export { metadata } from "@/app/groups/page";

// Floodlight P1 slice p1-s3: wraps app/groups/page.tsx -- WC26 only (see
// lib/sports.ts's `enabled` flags); the legacy component takes no params.
export default async function CompGroupsPage({
  params,
}: {
  params: Promise<{ comp: string }>;
}) {
  const { comp } = await params;
  if (!isWiredCompetition(comp)) notFound();
  return <LegacyGroupsPage />;
}
