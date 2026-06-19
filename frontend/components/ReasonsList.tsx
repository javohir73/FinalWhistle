/** "Why this prediction" list (explainable AI). */
export function ReasonsList({ reasons }: { reasons: string[] }) {
  if (!reasons.length) return null;
  return (
    <ul className="space-y-2.5">
      {reasons.map((r, i) => (
        <li key={i} className="flex gap-3 text-sm leading-relaxed">
          <span
            className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-win/15 text-lime-deep"
            aria-hidden
          >
            <svg viewBox="0 0 24 24" className="h-3 w-3" fill="none" stroke="currentColor" strokeWidth="3">
              <path d="M5 12.5l4.5 4.5L19 6.5" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          <span className="text-foreground">{r}</span>
        </li>
      ))}
    </ul>
  );
}
