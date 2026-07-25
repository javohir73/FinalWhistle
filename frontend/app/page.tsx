import type { Metadata } from "next";
import { APP_NAME } from "@/lib/constants";
import { renderHomePage } from "./HomePageContent";

export const metadata: Metadata = {
  title: `World Cup 2026 predictions — ${APP_NAME}`,
  description: "Fixtures, standings, and explainable predictions for World Cup 2026.",
};

export default async function HomePage() {
  return renderHomePage();
}
