import { cn } from "@/lib/utils";

/** Shared loading-skeleton primitives. Pure presentation, no client hooks —
 *  safe to render in Server Components (route `loading.tsx` fallbacks) as well
 *  as inside client islands. The shimmer sweep and its reduced-motion gate live
 *  on the `skeleton` class in globals.css. */

/** One shimmer block. Composes the `skeleton` class with caller layout classes.
 *  `aria-hidden` because a shimmer block carries no meaning on its own — the
 *  announcing `role="status"` lives on the surrounding SkeletonScreen. */
export function Skeleton({ className }: { className?: string }) {
  return <div aria-hidden className={cn("skeleton", className)} />;
}

/** Status wrapper for a whole loading view. Mirrors States.Loading's a11y
 *  contract so each `loading.tsx` announces exactly one status to AT. */
export function SkeletonScreen({
  label = "Loading…",
  children,
}: {
  label?: string;
  children: React.ReactNode;
}) {
  return (
    <div role="status" aria-label={label}>
      {children}
    </div>
  );
}

/** The six-card glass grid States.Loading draws — shared by the football and
 *  NRL list loaders so they don't each hand-roll the card markup. */
export function SkeletonCardGrid() {
  return (
    <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
      {Array.from({ length: 6 }).map((_, i) => (
        <div key={i} className="glass rounded-2xl p-4">
          <Skeleton className="mb-4 h-3 w-20 rounded" />
          <div className="mb-2.5 flex items-center gap-2.5">
            <Skeleton className="h-6 w-6 rounded-full" />
            <Skeleton className="h-4 w-28 rounded" />
          </div>
          <div className="mb-4 flex items-center gap-2.5">
            <Skeleton className="h-6 w-6 rounded-full" />
            <Skeleton className="h-4 w-24 rounded" />
          </div>
          <Skeleton className="h-2.5 w-full rounded-full" />
          <div className="mt-4 flex justify-between border-t border-border pt-3">
            <Skeleton className="h-4 w-24 rounded" />
            <Skeleton className="h-5 w-10 rounded" />
          </div>
        </div>
      ))}
    </div>
  );
}

/** Standings / ladder table placeholder: a header bar plus `rows` fixed-height
 *  rows. Heights and widths are fixed so the skeleton reserves the same box the
 *  real table fills — no layout shift when data lands. */
export function SkeletonRows({ rows = 8 }: { rows?: number }) {
  return (
    <div className="glass rounded-2xl p-4">
      <Skeleton className="mb-3 h-4 w-32 rounded" />
      <div className="space-y-2">
        {Array.from({ length: rows }).map((_, i) => (
          <Skeleton key={i} className="h-9 w-full rounded-lg" />
        ))}
      </div>
    </div>
  );
}
