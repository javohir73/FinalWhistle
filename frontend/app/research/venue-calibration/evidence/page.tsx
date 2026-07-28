import type { Metadata } from "next";
import Link from "next/link";
import data from "@/lib/venue-audit-data.json";

export const metadata: Metadata = {
  title: "Venue calibration evidence — FinalWhistle",
  description: "Inputs, method, reproducibility, and limitations for the World Cup venue audit.",
};

export default function VenueCalibrationEvidencePage() {
  return (
    <article className="fade-up mx-auto max-w-3xl space-y-8">
      <header>
        <p className="text-xs font-bold uppercase tracking-wider text-lime-deep">Evidence card</p>
        <h1 className="mt-2 font-display text-4xl font-extrabold tracking-tight">
          World Cup venue calibration
        </h1>
        <p className="mt-3 text-muted">Frozen inputs, deterministic calculations, and scope limits.</p>
      </header>

      <dl className="glass space-y-4 rounded-2xl p-5 text-sm">
        <Evidence label="Study" value={data.study} />
        <Evidence label="Frozen input" value={data.generated_from} code />
        <Evidence label="Input SHA-256" value={data.input_sha256} code breakAll />
        <Evidence label="Reproduce" value="PYTHONPATH=backend:. python -m pipeline.publish_venue_audit" code />
        <Evidence label="Bootstrap" value={`${data.method.bootstrap.samples.toLocaleString()} match resamples; seed ${data.method.bootstrap.seed}`} />
      </dl>

      <section>
        <h2 className="font-display text-lg font-bold">Method and limitations</h2>
        <dl className="mt-4 space-y-3 text-sm text-muted">
          <Evidence label="Population" value={data.method.population} />
          <Evidence label="Grading" value={data.method.grading} />
          <Evidence label="De-vigging" value={data.method.devigging} />
          <Evidence label="Snapshots" value={data.method.snapshots} />
        </dl>
        <ul className="mt-5 list-disc space-y-2 pl-5 text-sm text-muted">
          {data.method.limitations.map((limitation) => <li key={limitation}>{limitation}</li>)}
        </ul>
      </section>

      <p className="text-sm text-muted">
        <Link className="text-lime-deep underline" href="/research/venue-calibration">Return to the audit</Link>.
        This evidence is information and research only, not betting advice.
      </p>
    </article>
  );
}

function Evidence({ label, value, code = false, breakAll = false }: { label: string; value: string; code?: boolean; breakAll?: boolean }) {
  return (
    <div>
      <dt className="font-bold text-foreground">{label}</dt>
      <dd className={`mt-1 text-muted ${breakAll ? "break-all" : ""}`}>
        {code ? <code>{value}</code> : value}
      </dd>
    </div>
  );
}
