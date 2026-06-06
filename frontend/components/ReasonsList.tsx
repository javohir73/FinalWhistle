/** "Why this prediction" bullet list (PRD §12, explainable AI). */
export function ReasonsList({ reasons }: { reasons: string[] }) {
  if (!reasons.length) return null;
  return (
    <ul className="space-y-2">
      {reasons.map((r, i) => (
        <li key={i} className="flex gap-2 text-sm">
          <span aria-hidden className="text-win">
            ✓
          </span>
          <span>{r}</span>
        </li>
      ))}
    </ul>
  );
}
