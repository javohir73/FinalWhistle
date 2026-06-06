/** Shared loading / error / empty UI states (PRD 6.8). */
export function Loading({ label = "Loading…" }: { label?: string }) {
  return (
    <p role="status" className="py-12 text-center text-foreground/50">
      {label}
    </p>
  );
}

export function ErrorState({ message }: { message: string }) {
  return (
    <div role="alert" className="rounded-lg border border-loss/30 bg-loss/5 p-4 text-loss">
      <p className="font-medium">Something went wrong.</p>
      <p className="mt-1 text-sm text-loss/80">{message}</p>
      <p className="mt-2 text-sm text-foreground/60">
        Is the backend running? Check the API URL.
      </p>
    </div>
  );
}

export function Empty({ label = "Nothing to show yet." }: { label?: string }) {
  return <p className="py-12 text-center text-foreground/50">{label}</p>;
}
