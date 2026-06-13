/** @type {import('next').NextConfig} */
const IS_PROD = process.env.NODE_ENV === "production";
const API_ORIGIN =
  process.env.NEXT_PUBLIC_API_URL ||
  (IS_PROD ? "https://pitchprophet-api.onrender.com" : "http://localhost:8000");

// Content-Security-Policy. 'unsafe-inline' is needed for Next's inline bootstrap
// + styled JSX; flagcdn is the flag image host. The backend is reached through the
// same-origin /backend-api proxy, so connect-src only needs 'self' (+ Sentry).
// Applied in production only so dev HMR (eval + websockets) keeps working.
const csp = [
  "default-src 'self'",
  "base-uri 'self'",
  "object-src 'none'",
  "frame-ancestors 'none'",
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

const baseSecurityHeaders = [
  { key: "X-Frame-Options", value: "DENY" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  {
    key: "Permissions-Policy",
    value: "camera=(), microphone=(), geolocation=(), browsing-topics=()",
  },
];

const nextConfig = {
  reactStrictMode: true,
  eslint: {
    // Linting runs as its own CI step (`npm run lint`); don't re-run it during
    // `next build` so build failures and lint failures stay separate concerns.
    ignoreDuringBuilds: true,
  },
  async headers() {
    const headers = [...baseSecurityHeaders];
    if (process.env.NODE_ENV === "production") {
      headers.unshift({ key: "Content-Security-Policy", value: csp });
    }
    return [{ source: "/:path*", headers }];
  },
  async redirects() {
    return [{ source: "/how-it-works", destination: "/about", permanent: true }];
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
