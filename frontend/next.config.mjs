/** @type {import('next').NextConfig} */
const IS_PROD = process.env.NODE_ENV === "production";
const API_ORIGIN =
  process.env.NEXT_PUBLIC_API_URL ||
  (IS_PROD ? "https://pitchprophet-api.onrender.com" : "http://localhost:8000");

// Content-Security-Policy. 'unsafe-inline' is needed for Next's inline bootstrap
// + styled JSX; flagcdn is the flag image host. The backend is reached through the
// same-origin /backend-api proxy, so connect-src only needs 'self' (+ Sentry).
// Applied in production only so dev HMR (eval + websockets) keeps working.
//
// `frame-ancestors` differs between the two CSPs below: everywhere except
// /embed it's 'none' (nothing may iframe us); on /embed it's '*' (see
// buildCsp / the /embed headers rule further down) since /embed/[matchId] is
// the partner-embeddable prediction card and must be iframeable anywhere.
function buildCsp(frameAncestors) {
  return [
    "default-src 'self'",
    "base-uri 'self'",
    "object-src 'none'",
    `frame-ancestors ${frameAncestors}`,
    "form-action 'self'",
    "img-src 'self' data: https://flagcdn.com",
    "script-src 'self' 'unsafe-inline'",
    "style-src 'self' 'unsafe-inline'",
    "font-src 'self' data:",
    "connect-src 'self' https://*.ingest.sentry.io https://*.ingest.us.sentry.io https://*.ingest.de.sentry.io",
    "frame-src 'self'",
    "manifest-src 'self'",
    "worker-src 'self' blob:",
  ].join("; ");
}
const csp = buildCsp("'none'");
const embedCsp = buildCsp("*");

const baseSecurityHeaders = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), browsing-topics=()",
  },
];

// Same as baseSecurityHeaders except X-Frame-Options is dropped entirely —
// /embed/[matchId] is meant to be iframed by partner sites, so DENY (or any
// ALLOW-FROM value, which modern browsers ignore anyway) would defeat the
// feature. frame-ancestors * (in embedCsp above) is the modern replacement
// that actually permits arbitrary embedding.
const embedSecurityHeaders = baseSecurityHeaders.filter(
  (h) => h.key !== "X-Frame-Options",
);

const nextConfig = {
  reactStrictMode: true,
  eslint: {
    // Linting runs as its own CI step (`npm run lint`); don't re-run it during
    // `next build` so build failures and lint failures stay separate concerns.
    ignoreDuringBuilds: true,
  },
  async headers() {
    const headers = [...baseSecurityHeaders];
    const embedHeaders = [...embedSecurityHeaders];
    if (process.env.NODE_ENV === "production") {
      headers.unshift({ key: "Content-Security-Policy", value: csp });
      embedHeaders.unshift({ key: "Content-Security-Policy", value: embedCsp });
    }
    return [
      // Next's headers() rules stack (a later matching rule can only ADD
      // headers, never unset one set by an earlier rule), so the embed
      // exception can't be a second rule layered on top of a catch-all — the
      // catch-all itself must exclude /embed. This regex source matches every
      // path except "/embed" and "/embed/...". Verified against Next's
      // bundled path-to-regexp: '/', '/matches' etc. match; '/embed',
      // '/embed/97' don't; '/embedded-thing' still matches (correctly keeps
      // the strict headers) since the lookahead requires "embed" be followed
      // by "/" or end-of-string.
      { source: "/((?!embed(?:/|$)).*)", headers },
      { source: "/embed/:path*", headers: embedHeaders },
    ];
  },
  async redirects() {
    return [
      { source: "/how-it-works", destination: "/about", permanent: true },
      { source: "/my-bracket", destination: "/brackets", permanent: false },
    ];
  },
  // Same-origin proxy to the backend. Client-side API calls go to /backend-api/*
  // so authenticated requests carry the session cookie (SameSite=Lax) — a cookie
  // set by the Render host would be third-party to Vercel and never sent. Server
  // components still call the backend directly (server-to-server). Works in
  // `next dev` too, so the full auth round trip is testable locally.
  async rewrites() {
    return [
      { source: "/backend-api/:path*", destination: `${API_ORIGIN}/:path*` },
    ];
  },
};

export default nextConfig;
