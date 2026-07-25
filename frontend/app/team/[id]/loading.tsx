import { Skeleton, SkeletonScreen, SkeletonRows } from "@/components/Skeleton";

/** Route-level fallback for /team/[id] (App Router). page.tsx fans out to the
 *  team, group, fixtures and odds feeds before it can render, so a cold team
 *  page can stall — this reserves the box in the meantime. Mirrors the max-w-3xl
 *  column: the crest-banner header (back link, 56px crest, name + meta, stat
 *  tiles) then the stacked outlook / form / fixtures cards. */
export default function TeamLoading() {
  return (
    <SkeletonScreen label="Loading team…">
      <div className="mx-auto max-w-3xl space-y-6">
        {/* Crest banner — matches TeamHeader's edge-to-edge -mx band + border. */}
        <div className="-mx-4 border-b border-border px-4 pb-4 pt-1 sm:-mx-5 sm:px-5">
          <Skeleton className="h-6 w-28 rounded" />
          <div className="mt-1 flex items-center gap-3.5">
            <Skeleton className="h-14 w-14 rounded-full" />
            <div className="min-w-0 flex-1">
              <Skeleton className="h-7 w-44 rounded" />
              <Skeleton className="mt-2 h-4 w-40 rounded" />
            </div>
          </div>
          <div className="mt-3.5 flex gap-2">
            <Skeleton className="h-[52px] flex-1 rounded-[12px]" />
            <Skeleton className="h-[52px] flex-1 rounded-[12px]" />
          </div>
        </div>

        {/* ML outlook — label + 2×2 odds-tile grid. */}
        <div className="glass rounded-2xl p-6">
          <Skeleton className="mb-2 h-3 w-24 rounded" />
          <Skeleton className="mb-4 h-6 w-3/4 rounded" />
          <div className="grid grid-cols-2 gap-2">
            {Array.from({ length: 4 }).map((_, i) => (
              <Skeleton key={i} className="h-16 rounded-2xl" />
            ))}
          </div>
        </div>

        {/* Recent form / fixtures — stacked rows. */}
        <SkeletonRows rows={4} />
      </div>
    </SkeletonScreen>
  );
}
