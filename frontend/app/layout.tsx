import type { Metadata } from "next";
import { Bricolage_Grotesque, Hanken_Grotesk } from "next/font/google";
import Link from "next/link";
import "./globals.css";
import { APP_NAME } from "@/lib/constants";
import { DisclaimerBanner } from "@/components/DisclaimerBanner";

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

const NAV = [
  { href: "/matches", label: "Matches" },
  { href: "/groups", label: "Groups" },
  { href: "/brackets", label: "Brackets" },
  { href: "/about", label: "How it works" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${display.variable} ${body.variable}`}>
      <body className="min-h-screen font-sans antialiased">
        <DisclaimerBanner />
        <header className="sticky top-0 z-50 border-b border-border/60 bg-background/70 backdrop-blur-xl">
          <nav className="mx-auto flex max-w-6xl items-center justify-between px-5 py-3.5">
            <Link href="/" className="group flex items-center gap-2.5">
              <span className="grid h-8 w-8 place-items-center rounded-lg bg-win/15 text-win ring-1 ring-win/30 transition group-hover:bg-win/25">
                <svg viewBox="0 0 24 24" className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth="2.2">
                  <path d="M12 2l3 6 6 .8-4.5 4.2 1.2 6L12 17l-5.9 2 1.2-6L3 8.8 9 8z" strokeLinejoin="round" />
                </svg>
              </span>
              <span className="font-display text-lg font-extrabold tracking-tight">
                {APP_NAME}
              </span>
            </Link>
            <div className="flex items-center gap-1 text-sm">
              {NAV.map((n) => (
                <Link
                  key={n.href}
                  href={n.href}
                  className="rounded-lg px-3 py-1.5 text-muted transition hover:bg-surface-2/60 hover:text-foreground"
                >
                  {n.label}
                </Link>
              ))}
            </div>
          </nav>
        </header>
        <main className="mx-auto max-w-6xl px-5 py-8">{children}</main>
        <footer className="mx-auto mt-16 max-w-6xl px-5 py-10 text-center text-xs text-muted/70">
          <span className="font-display font-bold text-muted">{APP_NAME}</span>{" "}
          · Explainable World Cup 2026 predictions · For analytics and
          entertainment only. Not betting advice.
        </footer>
      </body>
    </html>
  );
}
