/** Shared loading / error / empty UI states with premium skeletons. */
export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <div role="status" aria-label={label}>
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {Array.from({ length: 6 }).map((_, i) => (
          <div key={i} className="glass rounded-2xl p-4">
            <div className="skeleton mb-4 h-3 w-20 rounded" />
            <div className="mb-2.5 flex items-center gap-2.5">
              <div className="skeleton h-6 w-6 rounded-full" />
              <div className="skeleton h-4 w-28 rounded" />
            </div>
            <div className="mb-4 flex items-center gap-2.5">
              <div className="skeleton h-6 w-6 rounded-full" />
              <div className="skeleton h-4 w-24 rounded" />
            </div>
            <div className="skeleton h-2.5 w-full rounded-full" />
            <div className="mt-4 flex justify-between border-t border-border pt-3">
              <div className="skeleton h-4 w-24 rounded" />
              <div className="skeleton h-5 w-10 rounded" />
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div
      role="alert"
      className="glass rounded-2xl border-loss/30 p-6 text-center"
    >
      <p className="font-display text-lg font-bold text-loss">Something went wrong</p>
      <p className="mt-1 text-sm text-muted">{message}</p>
      <p className="mt-3 text-sm text-muted/80">
        The prediction service may be waking up — try again in a moment.
      </p>
    </div>
  );
}

export function Empty({
  label = "Nothing to show yet.",
  action,
}: {
  label?: string;
  action?: React.ReactNode;
}) {
  return (
    <div className="glass rounded-2xl p-12 text-center text-muted">
      {label}
      {action && <div className="mt-4 flex justify-center">{action}</div>}
    </div>
  );
}
