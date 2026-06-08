import type { Metadata, Viewport } from "next";
import { Bricolage_Grotesque, Hanken_Grotesk } from "next/font/google";
import "./globals.css";
import { APP_NAME } from "@/lib/constants";
import { DisclaimerBanner } from "@/components/DisclaimerBanner";
import { SiteNav } from "@/components/SiteNav";
import { BottomNav } from "@/components/BottomNav";
import { ServiceWorker } from "@/components/ServiceWorker";

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

export const metadata: Metadata = {
  title: `${APP_NAME} — FIFA World Cup 2026 Predictions`,
  description:
    "Explainable AI predictions for the FIFA World Cup 2026. For analytics and entertainment only.",
  applicationName: APP_NAME,
  appleWebApp: {
    capable: true,
    title: APP_NAME,
    statusBarStyle: "black-translucent",
  },
  other: { "mobile-web-app-capable": "yes" },
  icons: {
    icon: [
      { url: "/icon-192.png", sizes: "192x192", type: "image/png" },
      { url: "/icon-512.png", sizes: "512x512", type: "image/png" },
    ],
    apple: [{ url: "/apple-icon-180.png", sizes: "180x180", type: "image/png" }],
  },
};

export const viewport: Viewport = {
  themeColor: "#0a140e",
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable}`}>
      <body className="min-h-[100dvh] font-sans antialiased">
        <ServiceWorker />
        <div className="app-top sticky top-0 z-50 bg-background">
          <DisclaimerBanner />
          <SiteNav />
        </div>
        <main className="mx-auto max-w-6xl px-4 py-8 sm:px-5">{children}</main>
        <footer className="mx-auto mt-16 max-w-6xl px-5 pb-24 pt-10 text-center text-xs text-muted/70 sm:pb-10">
          <span className="font-display font-bold text-muted">{APP_NAME}</span>{" "}
          · Explainable World Cup 2026 predictions · For analytics and
          entertainment only. Not betting advice.
        </footer>
        <BottomNav />
      </body>
    </html>
  );
}
