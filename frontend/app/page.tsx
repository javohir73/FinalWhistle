"use client";

import { useEffect, useState } from "react";
import { getHealth, type HealthResponse } from "@/lib/api";
import { APP_NAME } from "@/lib/constants";

type Status =
  | { kind: "loading" }
  | { kind: "ok"; data: HealthResponse }
  | { kind: "error"; message: string };

/** Temporary scaffold homepage (task 1.6). It proves the frontend can reach the
 *  backend by calling /api/health. The real dashboard is built in task 6.0. */
export default function HomePage() {
  const [status, setStatus] = useState<Status>({ kind: "loading" });

  useEffect(() => {
    getHealth()
      .then((data) => setStatus({ kind: "ok", data }))
      .catch((err) => setStatus({ kind: "error", message: String(err) }));
  }, []);

  return (
    <main className="mx-auto max-w-xl px-6 py-16">
      <h1 className="text-3xl font-bold">{APP_NAME}</h1>
      <p className="mt-2 text-foreground/70">
        FIFA World Cup 2026 prediction platform — scaffold.
      </p>

      <div className="mt-8 rounded-lg border border-border p-4">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-foreground/60">
          Backend connectivity
        </h2>
        {status.kind === "loading" && (
          <p className="mt-2" role="status">
            Checking backend…
          </p>
        )}
        {status.kind === "ok" && (
          <p className="mt-2 text-win" role="status">
            ✓ Connected — {status.data.app} ({status.data.model_version})
          </p>
        )}
        {status.kind === "error" && (
          <p className="mt-2 text-loss" role="alert">
            ✗ Cannot reach backend: {status.message}
          </p>
        )}
      </div>

      <p className="mt-8 text-xs text-foreground/50">
        For analytics and entertainment only. Not betting advice.
      </p>
    </main>
  );
}
