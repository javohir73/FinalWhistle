import type { Metadata } from "next";
import { Bricolage_Grotesque, Hanken_Grotesk } from "next/font/google";
import "./globals.css";
import { APP_NAME } from "@/lib/constants";
import { DisclaimerBanner } from "@/components/DisclaimerBanner";
import { SiteNav } from "@/components/SiteNav";

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
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable}`}>
      <body className="min-h-[100dvh] font-sans antialiased">
        <DisclaimerBanner />
        <SiteNav />
        <main className="mx-auto max-w-6xl px-4 py-8 sm:px-5">{children}</main>
        <footer className="mx-auto mt-16 max-w-6xl px-5 py-10 text-center text-xs text-muted/70">
          <span className="font-display font-bold text-muted">{APP_NAME}</span>{" "}
          · Explainable World Cup 2026 predictions · For analytics and
          entertainment only. Not betting advice.
        </footer>
      </body>
    </html>
  );
}
