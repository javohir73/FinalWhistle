import { Skeleton, SkeletonScreen, SkeletonRows } from "@/components/Skeleton";

/** Route-level fallback for /nrl (App Router). page.tsx fans out to the NRL
 *  matches, ladder and Origin feeds before it can render the hub, so a cold
 *  navigation stalls on those awaits — this reserves the box in the meantime.
 *  Mirrors the page's header, the FeatureHero glass panel and the two-column
 *  spine + mini-ladder grid so nothing shifts when the data lands (design doc:
 *  Floodlight P6 skeletons). Reuses the shared shimmer primitives. */
export default function NrlHomeLoading() {
  return (
    <SkeletonScreen label="Loading…">
      {/* "NRL · Season …" title + "Round … · model predictions" subtitle. */}
      <Skeleton className="h-8 w-64 rounded" />
      <Skeleton className="mt-1.5 h-4 w-52 rounded" />

      {/* FeatureHero — glass hero panel: eyebrow, giant win-prob figure, the
          thin W/D/L bar, two equal CTAs. */}
      <div className="glass mt-6 rounded-[16px] p-5">
        <Skeleton className="h-3 w-40 rounded" />
        <Skeleton className="mt-4 h-11 w-32 rounded" />
        <Skeleton className="mt-2 h-4 w-44 rounded" />
        <Skeleton className="mt-5 h-2.5 w-full rounded-full" />
        <div className="mt-5 flex gap-2">
          <Skeleton className="h-10 flex-1 rounded-xl" />
          <Skeleton className="h-10 flex-1 rounded-xl" />
        </div>
      </div>

      {/* This round's other fixtures fall down the spine (left); the mini ladder
          rides the 320px rail (right) — mirrors the md grid template. */}
      <div className="mt-6 grid gap-4 md:grid-cols-[1fr_320px]">
        <div className="space-y-3">
          <Skeleton className="h-4 w-28 rounded" />
          {Array.from({ length: 3 }).map((_, i) => (
            <div key={i} className="glass rounded-2xl p-4">
              <Skeleton className="mb-3 h-3 w-24 rounded" />
              <div className="mb-2.5 flex items-center gap-2.5">
                <Skeleton className="h-6 w-6 rounded-full" />
                <Skeleton className="h-4 w-28 rounded" />
              </div>
              <div className="flex items-center gap-2.5">
                <Skeleton className="h-6 w-6 rounded-full" />
                <Skeleton className="h-4 w-24 rounded" />
              </div>
            </div>
          ))}
        </div>
        <SkeletonRows rows={4} />
      </div>
    </SkeletonScreen>
  );
}
