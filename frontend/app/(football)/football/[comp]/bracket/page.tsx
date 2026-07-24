import { notFound } from "next/navigation";
import { isWiredCompetition } from "@/lib/sports";
import LegacyBracketsPage from "@/app/brackets/page";

export { generateMetadata } from "@/app/brackets/page";

// Floodlight P1 slice p1-s3: wraps app/brackets/page.tsx -- WC26 only (see
// lib/sports.ts's `enabled` flags; WC26 is also the only competition with
// hasBracket: true). The legacy component takes no params.
export default async function CompBracketPage({
  params,
}: {
  params: Promise<{ comp: string }>;
}) {
  const { comp } = await params;
  if (!isWiredCompetition(comp)) notFound();
  return <LegacyBracketsPage />;
}
