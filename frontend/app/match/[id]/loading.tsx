import { Skeleton, SkeletonScreen, SkeletonRows } from "@/components/Skeleton";

/** Route-level fallback for /match/[id] (App Router). The match centre makes
 *  five parallel API calls before it can render — the highest cold-start risk of
 *  the football surfaces — so this fallback matters most here. Mirrors the
 *  max-w-2xl column: the back/share row, the scoreboard hero (two crests + score
 *  + W/D/L bar), the Overview/Lineups tab strip, then one panel of rows. */
export default function MatchLoading() {
  return (
    <SkeletonScreen label="Loading match…">
      <div className="mx-auto max-w-2xl space-y-6">
        {/* Back link ↔ share button row. */}
        <div className="flex items-center justify-between">
          <Skeleton className="h-5 w-28 rounded" />
          <Skeleton className="h-9 w-9 rounded-full" />
        </div>

        {/* Scoreboard hero — crests, score, and the W/D/L probability bar. */}
        <div className="glass rounded-2xl p-6 text-center">
          <Skeleton className="mx-auto h-3 w-24 rounded" />
          <div className="mt-3 flex items-center justify-center gap-[18px]">
            <Skeleton className="h-11 w-11 rounded-full" />
            <Skeleton className="h-10 w-16 rounded" />
            <Skeleton className="h-11 w-11 rounded-full" />
          </div>
          <div className="mt-2 flex justify-center gap-[26px]">
            <Skeleton className="h-4 w-16 rounded" />
            <Skeleton className="h-4 w-16 rounded" />
          </div>
          <Skeleton className="mt-4 h-2.5 w-full rounded-full" />
          <div className="mt-2 flex justify-between">
            <Skeleton className="h-3 w-16 rounded" />
            <Skeleton className="h-3 w-14 rounded" />
            <Skeleton className="h-3 w-16 rounded" />
          </div>
        </div>

        {/* Overview / Lineups tab strip. */}
        <div className="flex gap-1 rounded-[14px] bg-surface-2 p-1">
          <Skeleton className="h-9 flex-1 rounded-[11px]" />
          <Skeleton className="h-9 flex-1 rounded-[11px]" />
        </div>

        {/* One panel of content rows. */}
        <SkeletonRows rows={5} />
      </div>
    </SkeletonScreen>
  );
}
