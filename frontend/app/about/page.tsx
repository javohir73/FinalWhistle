import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `How it works — ${APP_NAME}` };

const STEPS = [
  {
    title: "Elo ratings",
    body: "A strength score per nation, updated after every international since 1872. Hosts get a home-advantage bonus.",
  },
  {
    title: "Poisson goals model",
    body: "The Elo gap becomes expected goals, then the probability of every scoreline — giving win/draw/loss odds and a likely result.",
  },
  {
    title: "Monte-Carlo groups",
    body: "Each group is simulated thousands of times for qualification probabilities and predicted final tables.",
  },
];

export default function AboutPage() {
  return (
    <article className="fade-up mx-auto max-w-2xl space-y-8">
      <header>
        <h1 className="font-display text-4xl font-extrabold tracking-tight">
          How {APP_NAME} works
        </h1>
        <p className="mt-3 text-muted">
          Transparent, calibrated predictions — built in public, honest about both
          method and limits.
        </p>
      </header>

      <section className="grid gap-4 sm:grid-cols-3">
        {STEPS.map((s, i) => (
          <div key={s.title} className="glass rounded-2xl p-5">
            <div className="mb-2 font-display text-2xl font-extrabold text-win">
              0{i + 1}
            </div>
            <h2 className="font-display font-bold">{s.title}</h2>
            <p className="mt-1.5 text-sm text-muted">{s.body}</p>
          </div>
        ))}
      </section>

      <section className="glass rounded-2xl p-6">
        <h2 className="font-display text-lg font-bold">How accurate is it?</h2>
        <p className="mt-2 text-sm leading-relaxed text-foreground/90">
          Back-tested against the 2018 and 2022 World Cups, the model beats naive
          baselines on log-loss and is well-calibrated — a stated 60% chance happens
          about 60% of the time. It is honest about uncertainty: 2022 was an
          upset-heavy tournament, and no model foresees those reliably.
        </p>
      </section>

      <section className="glass rounded-2xl p-6">
        <h2 className="font-display text-lg font-bold">Data &amp; limitations</h2>
        <ul className="mt-2 list-inside list-disc space-y-1.5 text-sm text-muted">
          <li>Free, open data only: historical results, FIFA rankings, the official WC2026 draw.</li>
          <li>Team-level model — player injuries and form are not yet modeled.</li>
          <li>No live in-game updates yet; knockout bracket simulation is coming.</li>
        </ul>
      </section>

      <section className="glass rounded-2xl border-gold/20 bg-gold/[0.04] p-6">
        <h2 className="font-display text-lg font-bold text-gold">Disclaimer</h2>
        <p className="mt-2 text-sm leading-relaxed text-foreground/90">
          This platform is for analytics, research, and entertainment only. It is{" "}
          <strong>not betting advice</strong> and does not guarantee outcomes.
          Predictions are probabilistic. If you choose to gamble, do so responsibly
          and within the law of your jurisdiction (18+/21+).
        </p>
      </section>
    </article>
  );
}
