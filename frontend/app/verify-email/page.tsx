import { Suspense } from "react";
import type { Metadata } from "next";
import { APP_NAME } from "@/lib/constants";
import { VerifyEmailClient } from "./VerifyEmailClient";

export const metadata: Metadata = {
  title: `Verify email — ${APP_NAME}`,
  robots: { index: false, follow: false },
};

/** useSearchParams() requires a Suspense boundary in the App Router. */
export default function VerifyEmailPage() {
  return (
    <Suspense fallback={null}>
      <VerifyEmailClient />
    </Suspense>
  );
}
