import type { Metadata, Viewport } from "next";
import Link from "next/link";
import { Bricolage_Grotesque, Hanken_Grotesk } from "next/font/google";
import "./globals.css";
import { APP_NAME, SITE_URL } from "@/lib/constants";
import { Wordmark } from "@/components/Logo";
import { DisclaimerBanner } from "@/components/DisclaimerBanner";
import { OfflineBanner } from "@/components/OfflineBanner";
import { HideOnEmbed } from "@/components/HideOnEmbed";
import { SiteNav } from "@/components/SiteNav";
import { BottomNav } from "@/components/BottomNav";
import { InstallAppPrompt } from "@/components/InstallAppPrompt";
import { ActivityPing } from "@/components/ActivityPing";
import { ServiceWorker } from "@/components/ServiceWorker";
import { SentryInit } from "@/components/SentryInit";
import { AuthProvider } from "@/components/AuthProvider";
import { TournamentProvider } from "@/components/TournamentProvider";
import { getTournament } from "@/lib/tournament";
import { Analytics } from "@vercel/analytics/next";

const display = Bricolage_Grotesque({
  subsets: ["latin"],
  variable: "--font-display",
  display: "swap",
});
const body = Hanken_Grotesk({
  subsets: ["latin"],
  variable: "--font-body",
  display: "swap",
});

export async function generateMetadata(): Promise<Metadata> {
  const tournament = await getTournament();
  return {
    metadataBase: new URL(SITE_URL),
    title: `${APP_NAME} — ${tournament.name} Predictions`,
    description: `Explainable predictions for the ${tournament.name} from FinalWhistle's in-house ML model. For analytics and entertainment only.`,
    applicationName: APP_NAME,
    twitter: { card: "summary_large_image" },
    appleWebApp: {
      capable: true,
      title: APP_NAME,
      statusBarStyle: "default",
    },
    other: { "mobile-web-app-capable": "yes" },
    icons: {
      icon: [
        { url: "/icon.svg", type: "image/svg+xml" },
        { url: "/icon-192.png", sizes: "192x192", type: "image/png" },
        { url: "/icon-512.png", sizes: "512x512", type: "image/png" },
      ],
      apple: [{ url: "/apple-icon-180.png", sizes: "180x180", type: "image/png" }],
    },
  };
}

export const viewport: Viewport = {
  themeColor: "#0d1118",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default async function RootLayout({ children }: { children: React.ReactNode }) {
  const tournament = await getTournament();
  return (
    <html lang="en" className={`${display.variable} ${body.variable}`}>
      <head>
        {/* Warm the flag CDN connection: the country chooser fires ~48 flag
            requests at once on first paint, so the early TLS handshake cuts
            transient drops. */}
        <link rel="preconnect" href="https://flagcdn.com" crossOrigin="" />
        <link rel="dns-prefetch" href="https://flagcdn.com" />
      </head>
      <body className="min-h-[100dvh] font-sans antialiased">
        <ServiceWorker />
        <SentryInit />
        <TournamentProvider tournament={tournament}>
          <AuthProvider>
            <a href="#main" className="skip-link glass rounded-lg px-4 py-2 text-sm font-semibold">
              Skip to content
            </a>
            <div className="app-top sticky top-0 z-50 bg-background">
              <HideOnEmbed>
                <DisclaimerBanner />
              </HideOnEmbed>
              <SiteNav />
              <OfflineBanner />
            </div>
            <main
              id="main"
              className="mx-auto max-w-6xl px-4 pb-[calc(env(safe-area-inset-bottom)+72px)] pt-8 sm:px-5 sm:pb-8"
            >
              {children}
            </main>
            {/* Bottom padding clears the fixed mobile tab bar + the iPhone home
                indicator (safe-area inset is 0 on desktop/non-notched devices). */}
            <HideOnEmbed>
              <footer className="mx-auto mt-16 max-w-6xl px-5 pb-[calc(6.5rem+env(safe-area-inset-bottom))] pt-10 text-center text-xs text-muted sm:pb-10">
                <Wordmark className="font-bold" />{" "}
                · Explainable {tournament.name} predictions · For analytics and
                entertainment only. Not betting advice.
                <span className="mt-1.5 block">
                  <Link href="/methodology" className="underline-offset-2 hover:text-foreground hover:underline">
                    Methodology
                  </Link>{" "}
                  ·{" "}
                  <Link href="/privacy" className="underline-offset-2 hover:text-foreground hover:underline">
                    Privacy
                  </Link>{" "}
                  ·{" "}
                  <Link href="/terms" className="underline-offset-2 hover:text-foreground hover:underline">
                    Terms &amp; support
                  </Link>
                </span>
              </footer>
            </HideOnEmbed>
            <BottomNav />
            <InstallAppPrompt />
            <ActivityPing />
          </AuthProvider>
        </TournamentProvider>
        <Analytics />
      </body>
    </html>
  );
}
