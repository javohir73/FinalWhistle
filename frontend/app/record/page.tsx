import type { Metadata } from "next";
import { APP_NAME } from "@/lib/constants";
import { getModelRecordServer } from "@/lib/api";
import { RecordView } from "@/components/RecordView";

export const metadata: Metadata = {
  title: `Track record — ${APP_NAME}`,
  description:
    "The model's live, audited World Cup record: winner accuracy, exact scores, and calibration — every call graded pre-kickoff.",
};

export default async function RecordPage() {
  let record = null;
  try {
    record = await getModelRecordServer();
  } catch {
    record = null;
  }

  return (
    <article className="fade-up mx-auto max-w-2xl space-y-8">
      <header>
        <h1 className="font-display text-4xl font-extrabold tracking-tight">
          Track <span className="text-lime-deep">record</span>
        </h1>
        <p className="mt-3 text-muted">
          How the forecasts have actually held up on WC26 — every call graded
          pre-kickoff, wins and misses alike.
        </p>
      </header>
      {record ? (
        <RecordView record={record} />
      ) : (
        <section className="glass rounded-2xl p-6 text-center text-sm text-muted">
          The record is temporarily unavailable — please check back shortly.
        </section>
      )}
    </article>
  );
}
