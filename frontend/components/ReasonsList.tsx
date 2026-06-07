/** "Why this prediction" list (explainable AI). */
export function ReasonsList({ reasons }: { reasons: string[] }) {
  if (!reasons.length) return null;
  return (
    <ul className="space-y-2.5">
      {reasons.map((r, i) => (
        <li key={i} className="flex gap-3 text-sm leading-relaxed">
          <span
            className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-win/15 text-[11px] font-bold text-win ring-1 ring-win/30"
            aria-hidden
          >
            {i + 1}
          </span>
          <span className="text-foreground/90">{r}</span>
        </li>
      ))}
    </ul>
  );
}
