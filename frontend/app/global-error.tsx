"use client";

import { useEffect } from "react";

/**
 * Last-resort boundary for errors thrown in the root layout itself. It replaces
 * the whole document, so it ships its own minimal inline-styled markup (the app
 * stylesheet/layout is bypassed here). Rarely hit; route-level errors use error.tsx.
 */
export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error(error);
  }, [error]);

  return (
    <html lang="en">
      <body
        style={{
          margin: 0,
          minHeight: "100vh",
          display: "flex",
          flexDirection: "column",
          alignItems: "center",
          justifyContent: "center",
          gap: "1rem",
          padding: "2rem",
          textAlign: "center",
          background: "#f6f8f3",
          color: "#0f2117",
          fontFamily: "system-ui, -apple-system, Segoe UI, Roboto, sans-serif",
        }}
      >
        <h1 style={{ fontSize: "1.5rem", fontWeight: 800, margin: 0 }}>Something went wrong</h1>
        <p style={{ fontSize: "0.875rem", color: "#6b7c71", maxWidth: "28rem" }}>
          The app hit an unexpected error. Please try again.
        </p>
        <button
          type="button"
          onClick={reset}
          style={{
            cursor: "pointer",
            borderRadius: "0.75rem",
            border: "none",
            background: "#8fd633",
            color: "#123723",
            fontWeight: 700,
            padding: "0.5rem 1rem",
            fontSize: "0.875rem",
          }}
        >
          Try again
        </button>
      </body>
    </html>
  );
}
