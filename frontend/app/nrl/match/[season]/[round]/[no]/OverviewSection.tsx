import type { IntelSectionProps } from "./sections";

export function OverviewSection({ detail, probHistory }: IntelSectionProps) {
  const preview = detail.prediction?.preview_text ?? null;
  const points = probHistory?.points ?? [];

  return (
    <div className="glass rounded-2xl p-6">
      <h2 className="mb-3 font-display text-lg font-bold text-foreground">Overview</h2>
      {preview ? (
        preview.split("\n\n").map((para, i) => (
          <p key={i} className="mb-3 text-sm leading-relaxed text-foreground last:mb-0">
            {para}
          </p>
        ))
      ) : (
        <p className="text-sm text-muted">Preview not available yet.</p>
      )}
      {points.length >= 2 && (
        <div className="mt-5 border-t border-border pt-4">
          <p className="mb-2 text-xs font-semibold uppercase tracking-wider text-muted">
            Forecast movement
          </p>
          <ForecastLine points={points} />
        </div>
      )}
    </div>
  );
}

function ForecastLine({ points }: { points: { p_home: number | null }[] }) {
  const values = points.map((p) => p.p_home).filter((v): v is number => v != null);
  if (values.length < 2) return null;
  const w = 240;
  const h = 48;
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = max - min || 1;
  const pts = values
    .map((v, i) => `${(i / (values.length - 1)) * w},${h - 4 - ((v - min) / span) * (h - 8)}`)
    .join(" ");
  return (
    <svg viewBox={`0 0 ${w} ${h}`} className="h-12 w-full" aria-hidden="true">
      <polyline points={pts} fill="none" strokeWidth="2" className="stroke-lime-deep" />
    </svg>
  );
}
