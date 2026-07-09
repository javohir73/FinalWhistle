/** Tiny probability trend line. Pure SVG, no deps; hidden when <2 points. */
export function Sparkline({ values, tone }: { values: number[]; tone: "up" | "down" }) {
  if (values.length < 2) return null;
  const w = 44;
  const h = 16;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values
    .map((v, i) => `${(i / (values.length - 1)) * w},${h - 2 - ((v - min) / span) * (h - 4)}`)
    .join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-4 w-11 shrink-0" aria-hidden="true">
      <polyline
        points={pts}
        fill="none"
        strokeWidth="1.6"
        className={tone === "up" ? "stroke-lime-deep" : "stroke-loss"}
      />
    </svg>
  );
}
