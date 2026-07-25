import type { Metadata } from "next";
import { APP_NAME } from "@/lib/constants";
import { renderGroupsPage } from "./GroupsPageContent";

export const metadata: Metadata = {
  title: `Group tables — ${APP_NAME}`,
  description:
    "Live WC26 group standings with each team's model-projected chance of finishing in the top two.",
};

export default async function GroupsPage() {
  return renderGroupsPage();
}
