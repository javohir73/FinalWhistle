import { SkeletonCardGrid, SkeletonScreen } from "@/components/Skeleton";

/** Shared loading / error / empty UI states with premium skeletons. */
export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <SkeletonScreen label={label}>
      <SkeletonCardGrid />
    </SkeletonScreen>
  );
}

export function ErrorState({
  message,
  onRetry,
  hint = "The prediction service may be waking up — try again in a moment.",
}: {
  message: string;
  onRetry?: () => void;
  /** Secondary line under the message. Defaults to the prediction cold-start
   *  hint; pass a different string (or null) for non-prediction surfaces. */
  hint?: string | null;
}) {
  return (
    <div
      role="alert"
      className="glass rounded-2xl border-loss/30 p-6 text-center"
    >
      <p className="font-display text-lg font-bold text-loss">Something went wrong</p>
      <p className="mt-1 text-sm text-muted">{message}</p>
      {hint && <p className="mt-3 text-sm text-muted/80">{hint}</p>}
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="mt-4 rounded-lg bg-win px-4 py-2 text-sm font-bold text-pitch transition hover:brightness-110"
        >
          Try again
        </button>
      )}
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
