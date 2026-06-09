/** @type {import('next').NextConfig} */
const API_ORIGIN =
  process.env.NEXT_PUBLIC_API_URL || "https://pitchprophet-api.onrender.com";

// Content-Security-Policy. 'unsafe-inline' is needed for Next's inline bootstrap
// + styled JSX; flagcdn is the flag image host; the API origin is whitelisted for
// fetches. Applied in production only so dev HMR (eval + websockets) keeps working.
// Clerk (auth) loads its JS from the instance Frontend API and uses Cloudflare
// Turnstile for bot protection, so those hosts must be allowed when auth is on.
const CLERK = "https://*.clerk.accounts.dev";
const TURNSTILE = "https://challenges.cloudflare.com";
const csp = [
  "default-src 'self'",
  "base-uri 'self'",
  "object-src 'none'",
  "frame-ancestors 'none'",
  "form-action 'self'",
  `img-src 'self' data: https://flagcdn.com https://img.clerk.com ${CLERK}`,
  `script-src 'self' 'unsafe-inline' ${CLERK} ${TURNSTILE}`,
  "style-src 'self' 'unsafe-inline'",
  "font-src 'self' data:",
  `connect-src 'self' ${API_ORIGIN} ${CLERK} https://clerk-telemetry.com https://*.ingest.sentry.io https://*.ingest.us.sentry.io https://*.ingest.de.sentry.io`,
  `frame-src 'self' ${CLERK} ${TURNSTILE}`,
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
};

export default nextConfig;
