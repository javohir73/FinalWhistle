import type { ComponentType } from "react";
import type { NrlMatchDetail, NrlProbHistory } from "@/lib/types";
import { OverviewSection } from "./OverviewSection";
import { FormSection } from "./FormSection";
import { ModelSection } from "./ModelSection";
import StatsSection from "./StatsSection";
import MatchupSection from "./MatchupSection";
import LiveSection from "./LiveSection";
import ScorersSection from "./ScorersSection";

/** Props every Match Intelligence section component receives. Wave 1 ships
 *  overview/form/model; Wave 2 appends stats/matchup, Wave 3 appends
 *  scorers/live -- each a new entry below + a new self-contained component
 *  file, with NO edits to any Wave 1 section component. */
export interface IntelSectionProps {
  detail: NrlMatchDetail;
  probHistory: NrlProbHistory | null;
}

export type IntelSection = { id: string; label: string; render: ComponentType<IntelSectionProps> };

export const sections: IntelSection[] = [
  { id: "overview", label: "Overview", render: OverviewSection },
  { id: "form", label: "Form & H2H", render: FormSection },
  { id: "model", label: "Model", render: ModelSection },
  { id: "stats", label: "Stats", render: StatsSection },
  { id: "matchup", label: "Matchup", render: MatchupSection },
  { id: "live", label: "Live", render: LiveSection },
  { id: "scorers", label: "Scorers", render: ScorersSection },
];
