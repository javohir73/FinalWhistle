import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";
import { APP_NAME } from "@/lib/constants";
import { DisclaimerBanner } from "@/components/DisclaimerBanner";

export const metadata: Metadata = {
  title: `${APP_NAME} — FIFA World Cup 2026 Predictions`,
  description:
    "Explainable AI predictions for the FIFA World Cup 2026. For analytics and entertainment only.",
};

const NAV = [
  { href: "/", label: "Matches" },
  { href: "/groups", label: "Groups" },
  { href: "/about", label: "How it works" },
];

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen antialiased">
        <DisclaimerBanner />
        <header className="border-b border-border">
          <nav className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
            <Link href="/" className="text-lg font-bold">
              {APP_NAME}
            </Link>
            <div className="flex gap-4 text-sm">
              {NAV.map((n) => (
                <Link key={n.href} href={n.href} className="text-foreground/70 hover:text-foreground">
                  {n.label}
                </Link>
              ))}
            </div>
          </nav>
        </header>
        <main className="mx-auto max-w-5xl px-4 py-6">{children}</main>
        <footer className="mx-auto max-w-5xl px-4 py-8 text-center text-xs text-foreground/40">
          {APP_NAME} · For analytics and entertainment only. Not betting advice.
        </footer>
      </body>
    </html>
  );
}
