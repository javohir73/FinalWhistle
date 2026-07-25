import type { Metadata } from "next";
import { APP_NAME } from "@/lib/constants";
import { renderMatchesPage } from "./MatchesPageContent";

export const metadata: Metadata = {
  title: `Fixtures — ${APP_NAME}`,
  description:
    "Every WC26 fixture with live scores and the model's pre-kickoff win probabilities, filterable by upcoming, live, or finished.",
};

export default async function MatchesPage() {
  return renderMatchesPage();
}
