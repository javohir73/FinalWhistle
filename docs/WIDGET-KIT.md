# White-label prediction widget (embed kit)

An embeddable, brandable match-prediction card — the "why this prediction"
explainability layer that raw feed vendors don't offer (roadmap Phase 4,
product path). It renders server-side from the same data the app uses; the
embed itself needs no API key.

## Embed it

```html
<iframe
  src="https://fifa-wc26-prediction.vercel.app/embed/49?accent=lime&mode=light"
  title="FinalWhistle prediction — match 49"
  width="340" height="260" frameborder="0" loading="lazy"
  style="border:0;max-width:100%"></iframe>
```

Swap `49` for the match id. The card shows the teams, win/draw/loss
probabilities, the predicted score, the top "why" reasons, a confidence chip,
and a "not betting advice" disclaimer.

## URL & parameters

`/embed/{matchId}?accent=…&mode=…&compact=1&hideReasons=1`

| Param | Values | Default | Effect |
|---|---|---|---|
| `accent` | a named preset (`lime`, `green`, `amber`, `rose`, `gold`, `blue`, `violet`, `slate`) **or** a hex (`#1e88e5` / `1e88e5`) | brand deep-lime | accent colour (allow-listed / strict hex — untrusted input can't inject CSS) |
| `mode` | `light` \| `dark` | `light` | standalone light/dark palette (works in a bare iframe) |
| `compact` | `1` | off | tighter layout, fewer reasons |
| `hideReasons` | `1` | off | hide the "why" reasons row |

Unknown match / missing prediction / backend hiccup renders a small
"prediction unavailable" card — it never crashes inside the partner's page.

## Deploy prerequisite — allow cross-origin framing for `/embed/*`

The app ships hardened anti-clickjacking headers globally (`X-Frame-Options:
DENY` + CSP `frame-ancestors 'none'` in `frontend/next.config.mjs`), which by
design block ALL third-party framing — including this widget. To let partners
embed it, **relax those two frame controls for the `/embed/*` path only**,
keeping every other route locked down.

Because duplicate frame headers resolve to the most-restrictive value, the
global rule must **exclude** `/embed` (a negative-lookahead source) rather than
be overridden. Sketch:

- keep the non-frame security headers (X-Content-Type-Options, Referrer-Policy,
  Permissions-Policy) on every path;
- apply `X-Frame-Options: DENY` + CSP `frame-ancestors 'none'` to everything
  **except** `/embed/*`;
- on `/embed/:path*`, omit `X-Frame-Options` and set CSP `frame-ancestors` to
  `*` (public widget) or an explicit partner allow-list.

This is left as a deliberate, reviewed infra change — it relaxes clickjacking
protection for one public, read-only path — rather than shipped automatically.
The `/embed` route itself is safe to frame: read-only, no auth, no mutating
action, no session state.

## The app shell (chrome-free embed)

The `/embed/{id}` route currently renders inside the normal app shell (the top
disclaimer banner + nav + footer). For a fully white-label card, host the embed
under a chrome-free root layout. In the Next.js App Router the clean way is a
**route group with its own root layout** — move the site into `app/(site)/`
(keeping the chrome) and give `app/(embed)/` a bare root layout of just
`<html><body>` — so the embed escapes the chrome *without* forcing dynamic
rendering on the rest of the app (reading `headers()` in the shared root layout
would do that and cost the app its static/ISR rendering). This is a deliberate
layout refactor, left as a follow-up; the card component (`EmbedPredictionCard`)
and its theming are the reusable core and are shell-independent.

## Data & keys

The embed is a server component that fetches the match server-to-server, so it
needs no client API key and raises no CORS. The separate versioned data API
(`GET /v1/markets/{id}`) has an optional sandbox API-key gate (`API_KEYS_ALLOWED`,
`X-API-Key` header) — **off by default**; that gate is for programmatic B2B
consumers, not the iframe.
