import Link from "next/link";
import { APP_NAME } from "@/lib/constants";

export const metadata = {
  title: `Privacy policy — ${APP_NAME}`,
  description: `What ${APP_NAME} collects, why, and how to remove it.`,
};

const SECTIONS: { title: string; body: React.ReactNode }[] = [
  {
    title: "What we collect",
    body: (
      <>
        <p>
          <strong>Without an account</strong> — nothing personal. Your bracket and
          match picks live in your browser&apos;s local storage on your device.
          We see anonymous, aggregated usage analytics (page views and feature
          events via Vercel Analytics — no cookies, no cross-site tracking, no
          advertising identifiers).
        </p>
        <p className="mt-3">
          <strong>With an account</strong> — your email address, a display name if
          you set one, and a securely hashed password (argon2; we can never read
          it). Your saved bracket and match picks are stored against your
          account so they follow you across devices. If you join the
          leaderboard, the display name you choose and your bracket score are
          shown publicly — that is opt-in and clearly labelled.
        </p>
      </>
    ),
  },
  {
    title: "What we don't do",
    body: (
      <ul className="list-disc space-y-1.5 pl-5">
        <li>No selling or sharing of personal data with third parties.</li>
        <li>No advertising networks, no ad identifiers, no cross-app tracking.</li>
        <li>No precise location collection.</li>
        <li>No reading your contacts, photos, or anything else on your device.</li>
      </ul>
    ),
  },
  {
    title: "Security details",
    body: (
      <p>
        Sessions use HttpOnly cookies — no auth tokens are stored in scripts or
        local storage. To throttle break-in attempts we keep a one-way hash of
        the requesting IP for failed logins (the raw IP is never stored). At
        sign-up we record a coarse country/city derived from our hosting
        provider&apos;s request headers, used only for abuse prevention and
        aggregate stats. Error reports (Sentry) contain technical context, not
        your picks or identity.
      </p>
    ),
  },
  {
    title: "Your choices",
    body: (
      <p>
        You can play forever without an account. You can clear local picks by
        clearing site data in your browser. To delete an account and everything
        attached to it, contact us (below) from the account&apos;s email address
        and we&apos;ll remove it.
      </p>
    ),
  },
  {
    title: "Contact",
    body: (
      <p>
        Questions or deletion requests:{" "}
        <a className="text-win underline-offset-2 hover:underline" href="mailto:javohirazizov48@gmail.com">
          javohirazizov48@gmail.com
        </a>
        . See also our <Link className="text-win underline-offset-2 hover:underline" href="/terms">terms &amp; support</Link>.
      </p>
    ),
  },
];

export default function PrivacyPage() {
  return (
    <article className="fade-up mx-auto max-w-2xl space-y-8">
      <header>
        <h1 className="font-display text-4xl font-extrabold tracking-tight">Privacy policy</h1>
        <p className="mt-3 text-muted">
          {APP_NAME} is built to need as little of your data as possible. Last
          updated 12 June 2026.
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
