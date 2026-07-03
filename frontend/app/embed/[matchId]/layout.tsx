import type { Metadata } from "next";
import { APP_NAME } from "@/lib/constants";

/** Embed chrome — deliberately *minimal*. This route is meant to be iframed on
 *  partner sites, so it must NOT inherit the site nav / header / footer / banners
 *  that the root layout renders. The root layout still wraps this (fonts + the
 *  global CSS reset flow through its <html>), but here we render only a narrow,
 *  transparent, single-column shell around the widget so it drops cleanly into a
 *  host page of any background color.
 *
 *  Embeds must never be indexed on their own — the canonical experience lives at
 *  /match/[id]. */
export const metadata: Metadata = {
  title: `Prediction widget — ${APP_NAME}`,
  robots: { index: false, follow: false },
};

export default function EmbedLayout({ children }: { children: React.ReactNode }) {
  return (
    <div
      // Transparent background so the widget blends into the partner's page;
      // narrow column caps the width around the card's own 340px max. Font vars
      // are inherited from the root <html> (Bricolage / Hanken via next/font).
      style={{
        display: "flex",
        justifyContent: "center",
        width: "100%",
        maxWidth: 360,
        margin: "0 auto",
        padding: 8,
        background: "transparent",
        boxSizing: "border-box",
      }}
    >
      {children}
    </div>
  );
}
