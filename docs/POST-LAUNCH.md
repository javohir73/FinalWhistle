# Post-launch tasks & accepted risks

Tracking for work intentionally deferred until after the World Cup 2026 group
stage opens (June 11, 2026), so framework-level changes don't risk a
tournament-day regression.

## Accepted temporary risk: Next.js audit advisories

**Status:** Accepted until post-launch (target: review week of 2026-06-15).

`npm audit` reports 1 high + 1 moderate advisory against `next` (and a
transitive `postcss`). We are on **next@14.2.35**, the latest patch in the
14.2.x line. The remaining advisories were only fixed in the **15.x / 16.x**
lines, so the entire 14.2.x range is flagged regardless of patch level.

**Why this is an accepted temporary risk, not an open vulnerability:**

- No custom `middleware.ts` → middleware-bypass / middleware cache-poisoning
  advisories are not reachable.
- No `next/image` usage (flags render via plain `<img>`) → Image Optimizer DoS
  and disk-cache advisories are not reachable.
- No CSP nonces (we ship a static CSP) → the nonce-based XSS advisory is not
  reachable.
- No `beforeInteractive` scripts → that XSS advisory is not reachable.
- No i18n routing → the i18n middleware-bypass advisory is not reachable.
- Hosted on **Vercel** (not self-hosted), which mitigates the "self-hosted"
  classes at the platform/CDN layer.

The 14.2.18 → 14.2.35 bump already pulled in the CVE-2025-29927 middleware
auth-bypass fix and later 14.2.x security patches.

**Exit criteria:** completing the tracked Next 15/16 upgrade below clears the
audit; re-run `npm audit --omit=dev` and confirm 0 high/critical.

## Tracked task: Next.js 15/16 major upgrade

**Priority:** High (technical), post-launch.

Move off the 14.2.x line to the actively-patched major (15.x, then assess 16.x)
to clear the advisories above.

Breaking changes to handle:

- `params` / `searchParams` become async (Promise) — must `await` them in
  `generateMetadata` and in the dynamic pages: `app/match/[id]/page.tsx`,
  `app/team/[id]/page.tsx`, `app/groups/[id]/page.tsx`.
- `fetch` is no longer cached by default — we already pass explicit
  `next: { revalidate }`, so verify each call site still behaves as intended.
- React 19 becomes the default — pin React 18 first to isolate the Next bump,
  then upgrade React separately.

Verification gates for the upgrade PR:

- `npm test` green, `npm run build` green.
- Screenshot regression check on key routes: `/`, `/matches`, `/match/[id]`,
  `/groups/[id]`, `/team/[id]`, `/brackets`, `/methodology` (desktop + 390px).
- `npm audit --omit=dev` reports 0 high/critical.
