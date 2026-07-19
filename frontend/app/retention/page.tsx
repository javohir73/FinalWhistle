import type { Metadata } from "next";
import { APP_NAME } from "@/lib/constants";
import { getRetentionServer } from "@/lib/api";
import type { RetentionStats } from "@/lib/types";

export const metadata: Metadata = {
  title: `Retention — ${APP_NAME}`,
  description:
    "Anonymous device cohorts measured since the World Cup final — daily active devices and D1/D7/D14 retention, updated daily.",
};

const pct = (x: number | null) => (x == null ? "—" : `${x}%`);

export default async function RetentionPage() {
  let stats: RetentionStats | null = null;
  try {
    stats = await getRetentionServer();
  } catch {
    stats = null;
  }

  return (
    <article className="fade-up mx-auto max-w-2xl space-y-8">
      <header>
        <h1 className="font-display text-4xl font-extrabold tracking-tight">
          Retention <span className="text-lime-deep">stats</span>
        </h1>
        <p className="mt-3 text-muted">
          Anonymous device cohorts measured since the World Cup final — updates daily.
        </p>
      </header>

      {stats ? (
        <>
          <section className="glass grid grid-cols-2 gap-4 rounded-2xl p-6 text-center sm:grid-cols-3">
            <div>
              <p className="font-display text-2xl font-extrabold tabular-nums">{stats.since}</p>
              <p className="mt-1 text-xs text-muted">Since</p>
            </div>
            <div>
              <p className="font-display text-2xl font-extrabold tabular-nums">
                {stats.total_devices.toLocaleString()}
              </p>
              <p className="mt-1 text-xs text-muted">Total devices</p>
            </div>
          </section>

          <section className="glass rounded-2xl p-6">
            <h2 className="font-display text-lg font-bold">Daily active devices</h2>
            <p className="mt-1 text-sm text-muted">Last 30 days.</p>
            <div className="mt-4 max-h-80 overflow-y-auto overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left font-display text-[11px] uppercase tracking-wider text-muted">
                    <th className="py-1.5 pr-2 font-semibold">Day</th>
                    <th className="py-1.5 text-right font-semibold">Devices</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.dau.map((row) => (
                    <tr key={row.day} className="border-t border-border">
                      <td className="py-2 pr-2 tabular-nums">{row.day}</td>
                      <td className="py-2 text-right tabular-nums">{row.devices}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <section className="glass rounded-2xl p-6">
            <h2 className="font-display text-lg font-bold">Cohort retention</h2>
            <p className="mt-1 text-sm text-muted">
              Each row is the devices whose FIRST-ever visit was that day, and what
              share came back 1 / 7 / 14 days later. An em dash means that
              checkpoint hasn&apos;t happened yet.
            </p>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="text-left font-display text-[11px] uppercase tracking-wider text-muted">
                    <th className="py-1.5 pr-2 font-semibold">Day</th>
                    <th className="py-1.5 text-right font-semibold">Cohort</th>
                    <th className="py-1.5 text-right font-semibold">D1</th>
                    <th className="py-1.5 text-right font-semibold">D7</th>
                    <th className="py-1.5 text-right font-semibold">D14</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.cohorts.map((row) => (
                    <tr key={row.day} className="border-t border-border">
                      <td className="py-2 pr-2 tabular-nums">{row.day}</td>
                      <td className="py-2 text-right tabular-nums">{row.cohort_size}</td>
                      <td className="py-2 text-right tabular-nums">{pct(row.d1)}</td>
                      <td className="py-2 text-right tabular-nums">{pct(row.d7)}</td>
                      <td className="py-2 text-right tabular-nums">{pct(row.d14)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        </>
      ) : (
        <section className="glass rounded-2xl p-6 text-center text-sm text-muted">
          Retention stats are temporarily unavailable — please check back shortly.
        </section>
      )}
    </article>
  );
}
