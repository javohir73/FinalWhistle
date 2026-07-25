import type { Metadata } from "next";
import { APP_NAME } from "@/lib/constants";
import { PlatformHome } from "@/components/PlatformHome";

export const metadata: Metadata = {
  title: `${APP_NAME} — Sports predictions, clearly explained`,
  description:
    "Football and NRL predictions, fixtures, standings and model records in one place.",
};

export default function HomePage() {
  return <PlatformHome />;
}
