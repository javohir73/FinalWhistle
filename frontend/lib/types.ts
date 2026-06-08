/** API response types mirroring the backend Pydantic schemas (PRD §17, §11). */

export interface Teams {
  home: string;
  away: string;
}

export interface Probabilities {
  home_win: number;
  draw: number;
  away_win: number;
}

export interface PredictedScore {
  home: number | null;
  away: number | null;
  probability: number | null;
}

export interface FeatureWeight {
  name: string;
  weight: number;
}

export interface HeadToHead {
  matches: number;
  home_wins: number;
  draws: number;
  away_wins: number;
}

export interface Prediction {
  match_id: number;
  model_version: string;
  generated_at: string | null;
  teams: Teams;
  home_team_id: number | null;
  away_team_id: number | null;
  group: string | null;
  group_id: number | null;
  stage: string | null;
  is_neutral: boolean;
  kickoff_utc: string | null;
  venue: string | null;
  venue_city: string | null;
  venue_country: string | null;
  probabilities: Probabilities;
  predicted_score: PredictedScore;
  confidence: "High" | "Medium" | "Low" | null;
  reasons: string[];
  top_features: FeatureWeight[];
  head_to_head: HeadToHead;
  odds_comparison: { available: boolean };
  disclaimer: string;
}

export interface MatchSummary {
  match_id: number;
  stage: string;
  group: string | null;
  kickoff_utc: string | null;
  venue: string | null;
  venue_city: string | null;
  venue_country: string | null;
  is_neutral: boolean;
  status: "scheduled" | "in_play" | "finished";
  score_home: number | null;
  score_away: number | null;
  minute: number | null;
  teams: Teams;
  predicted_winner: string | null;
  probabilities: Probabilities | null;
  predicted_score: PredictedScore | null;
  confidence: "High" | "Medium" | "Low" | null;
}

export interface Team {
  id: number;
  name: string;
  country_code: string | null;
  confederation: string | null;
  fifa_rank: number | null;
  elo_rating: number | null;
  is_host: boolean;
}

export interface StandingRow {
  team_id: number;
  team: string;
  projected_points: number;
  projected_goals_for: number;
  projected_goal_diff: number;
  qualification_prob: number | null;
}

export interface Group {
  id: number;
  name: string;
  standings: StandingRow[];
}

export interface TournamentOdds {
  team_id: number;
  team: string;
  make_knockout: number | null;
  reach_r16: number | null;
  reach_qf: number | null;
  reach_sf: number | null;
  reach_final: number | null;
  win_title: number | null;
}

export interface FormResult {
  opponent: string;
  score_for: number;
  score_against: number;
  result: "W" | "D" | "L";
  date: string | null;
}

export interface TeamProfile {
  team: Team;
  group_id: number | null;
  group_name: string | null;
  recent_form: FormResult[];
  strengths: string[];
  weaknesses: string[];
}

export interface PredictionHistoryPoint {
  generated_at: string | null;
  model_version: string;
  home_win: number;
  draw: number;
  away_win: number;
}

export interface PredictionWithHistory {
  current: Prediction;
  history: PredictionHistoryPoint[];
}
