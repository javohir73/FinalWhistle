import { notFound } from "next/navigation";
import { isWiredCompetition } from "@/lib/sports";
import LegacyGroupDetailPage from "@/app/groups/[id]/page";

export { generateMetadata } from "@/app/groups/[id]/page";

// Floodlight P1 slice p1-s3: wraps app/groups/[id]/page.tsx. WC26-only guard
// on the body; generateMetadata re-exported above runs unguarded (harmless
// for an invalid comp, per the slice's ruling). The legacy page only reads
// params.id, so the wider { comp, id } promise passes straight through.
export default async function CompGroupDetailPage({
  params,
}: {
  params: Promise<{ comp: string; id: string }>;
}) {
  const { comp } = await params;
  if (!isWiredCompetition(comp)) notFound();
  return <LegacyGroupDetailPage params={params} />;
}
