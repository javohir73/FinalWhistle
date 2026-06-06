import { APP_NAME } from "@/lib/constants";

export const metadata = { title: `How it works — ${APP_NAME}` };

export default function AboutPage() {
  return (
    <article className="prose-sm max-w-2xl space-y-5">
      <h1 className="text-2xl font-bold">How {APP_NAME} works</h1>

      <p className="text-foreground/70">
        {APP_NAME} predicts FIFA World Cup 2026 outcomes and explains every
        prediction. It is built in public and designed to be transparent about
        both its method and its limits.
      </p>

      <section>
        <h2 className="font-semibold">The model</h2>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-foreground/70">
          <li>
            <strong>Elo ratings</strong> — a strength score per team, updated after
            every international match since 1872. Hosts get a home-advantage bonus.
          </li>
          <li>
            <strong>Poisson goals model</strong> — turns the Elo gap into expected
            goals, then the probability of every scoreline, giving win/draw/loss
            odds and a likely score.
          </li>
          <li>
            <strong>Group simulation</strong> — each group is simulated thousands of
            times for qualification probabilities.
          </li>
        </ul>
      </section>

      <section>
        <h2 className="font-semibold">How accurate is it?</h2>
        <p className="mt-2 text-sm text-foreground/70">
          Back-tested against the 2018 and 2022 World Cups, the model beats naive
          baselines on log-loss and is well-calibrated — a stated 60% chance
          happens about 60% of the time. It is honest about uncertainty: 2022 was
          an upset-heavy tournament, and no model foresees those reliably. Full
          numbers live in the project methodology document.
        </p>
      </section>

      <section>
        <h2 className="font-semibold">Data sources</h2>
        <p className="mt-2 text-sm text-foreground/70">
          Free and open data only: historical international results, FIFA rankings,
          and the official WC2026 draw. No paid feeds in this release.
        </p>
      </section>

      <section>
        <h2 className="font-semibold">Limitations</h2>
        <ul className="mt-2 list-disc space-y-1 pl-5 text-sm text-foreground/70">
          <li>Team-level only — player injuries and form are not yet modeled.</li>
          <li>No live in-game updates yet.</li>
          <li>Knockout bracket probabilities are coming in a later release.</li>
        </ul>
      </section>

      <section className="rounded-lg border border-border bg-foreground/5 p-4">
        <h2 className="font-semibold">Disclaimer</h2>
        <p className="mt-2 text-sm text-foreground/70">
          This platform is for analytics, research, and entertainment only. It is{" "}
          <strong>not betting advice</strong> and does not guarantee outcomes.
          Predictions are probabilistic. If you choose to gamble, do so
          responsibly and within the law of your jurisdiction (18+/21+).
        </p>
      </section>
    </article>
  );
}
