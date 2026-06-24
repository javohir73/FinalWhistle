import { Suspense } from "react";
import type { Metadata } from "next";
import { APP_NAME } from "@/lib/constants";
import { ResetPasswordClient } from "./ResetPasswordClient";

export const metadata: Metadata = {
  title: `Reset password — ${APP_NAME}`,
  robots: { index: false, follow: false },
};

/** useSearchParams() requires a Suspense boundary in the App Router. */
export default function ResetPasswordPage() {
  return (
    <Suspense fallback={null}>
      <ResetPasswordClient />
    </Suspense>
  );
}
