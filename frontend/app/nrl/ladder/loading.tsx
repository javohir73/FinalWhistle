import { Skeleton, SkeletonScreen, SkeletonRows } from "@/components/Skeleton";

/** Route-level fallback for /nrl/ladder (App Router). page.tsx awaits the NRL
 *  ladder + projections feeds before it can render the StandingsTable, so a cold
 *  navigation stalls on those awaits — this reserves the box. Mirrors the
 *  "NRL ladder" header plus the single glass ladder card: one SkeletonRows per
 *  club row so the tabular box is held and the ladder drops in without shifting
 *  (design doc: Floodlight P6 skeletons). Reuses the shared shimmer primitives. */
export default function NrlLadderLoading() {
  return (
    <SkeletonScreen label="Loading ladder…">
      {/* "NRL ladder · Season …" title + "Top 8 qualify" subtitle. */}
      <Skeleton className="h-8 w-72 rounded" />
      <Skeleton className="mt-1.5 h-4 w-48 rounded" />

      {/* The ladder itself: header bar + one row per club (17-club NRL season),
          inside the same glass card the StandingsTable fills. */}
      <div className="mt-6">
        <SkeletonRows rows={17} />
      </div>
    </SkeletonScreen>
  );
}
