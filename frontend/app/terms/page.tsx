import Link from "next/link";
import { APP_NAME } from "@/lib/constants";

export const metadata = {
  title: `Terms & support — ${APP_NAME}`,
  description: `${APP_NAME} terms of use and support contact.`,
};

const SECTIONS: { title: string; body: React.ReactNode }[] = [
  {
    title: "What FinalWhistle is",
    body: (
      <p>
        {APP_NAME} provides statistical predictions and interactive bracket play
        for the FIFA World Cup 2026, for <strong>analytics and entertainment
        only</strong>. Probabilities are model outputs, not promises — football
        keeps its own counsel. Nothing here is betting advice, and the app
        offers no wagering, no real-money play, and no prizes.
      </p>
    ),
  },
  {
    title: "Fair use",
    body: (
      <ul className="list-disc space-y-1.5 pl-5">
        <li>Free to use, with or without an account.</li>
        <li>
          Leaderboard display names are public — keep them civil; we may remove
          offensive names or entries that game the scoring.
        </li>
        <li>
          Don&apos;t abuse the service (scraping at scale, attacking the API,
          attempting to access other users&apos; accounts).
        </li>
      </ul>
    ),
  },
  {
    title: "Accounts",
    body: (
      <p>
        Accounts exist to save your bracket across devices and join the
        leaderboard. You are responsible for keeping your password safe;
        password reset is not yet self-serve — contact support if you&apos;re
        locked out. You can request account deletion at any time (see{" "}
        <Link className="text-lime-deep underline-offset-2 hover:underline" href="/privacy">privacy policy</Link>).
      </p>
    ),
  },
  {
    title: "No guarantees",
    body: (
      <p>
        The service is provided as-is. We aim for accuracy and uptime but
        guarantee neither — fixtures, scores, and model outputs can lag or err,
        and the service may change or pause. {APP_NAME} is not affiliated with
        or endorsed by FIFA.
      </p>
    ),
  },
  {
    title: "Support",
    body: (
      <p>
        Bugs, questions, account help:{" "}
        <a className="text-lime-deep underline-offset-2 hover:underline" href="mailto:javohirazizov48@gmail.com">
          javohirazizov48@gmail.com
        </a>
        . We read everything.
      </p>
    ),
  },
];

export default function TermsPage() {
  return (
    <article className="fade-up mx-auto max-w-2xl space-y-8">
      <header>
        <h1 className="font-display text-4xl font-extrabold tracking-tight">
          Terms &amp; support
        </h1>
        <p className="mt-3 text-muted">
          The short, honest version. Last updated 12 June 2026.
        </p>
      </header>

      {SECTIONS.map((s) => (
        <section key={s.title} className="glass rounded-2xl p-6">
          <h2 className="mb-3 font-display text-lg font-bold">{s.title}</h2>
          <div className="text-sm leading-relaxed text-foreground/90">{s.body}</div>
        </section>
      ))}
    </article>
  );
}
