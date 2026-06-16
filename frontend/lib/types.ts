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

/** Phase of play while a match is in progress (refines `status`). Null before
 *  kickoff and after the final whistle. */
export type LivePeriod =
  | "first_half"
  | "half_time"
  | "second_half"
  | "extra_time"
  | "penalty_shootout"
  | null;

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
  period: LivePeriod;
  injury_time: number | null;
  penalty_home: number | null;
  penalty_away: number | null;
  teams: Teams;
  predicted_winner: string | null;
  probabilities: Probabilities | null;
  predicted_score: PredictedScore | null;
  confidence: "High" | "Medium" | "Low" | null;
  /** In-play win probability given the live score and time left; present only
   *  while the match is live (else use the pre-match `probabilities`). */
  live_probabilities?: Probabilities | null;
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

// ---- Accounts / leaderboard ----
export interface LeaderboardRow {
  rank: number | null;
  display_name: string;
  champion: string | null;
  total_points: number;
  percentile: number | null;
  updated_at: string | null;
}

export interface SavedBracketScore {
  group_points: number;
  knockout_points: number;
  champion_bonus: number;
  total_points: number;
  rank: number | null;
}

export interface SavedBracket {
  id: number;
  visibility: string;
  display_name: string | null;
  champion_team_id: number | null;
  completion_pct: number;
  group_picks: { match_id: number; pick: "home" | "draw" | "away" }[];
  knockout_picks: { match_no: number; picked_team_id: number }[];
  score: SavedBracketScore | null;
  submitted_at: string | null;
  updated_at: string | null;
}

/** The account copy of the device-local per-match predictions. */
export interface SavedMatchPicks {
  picks: { match_id: number; pick: "home" | "draw" | "away" }[];
  updated_at: string | null;
}

// ---- Model performance record ----
export interface ModelRecordEntry {
  match_id: number;
  label: string;
  predicted_score: { home: number | null; away: number | null } | null;
  prob_assigned: number | null;
  winner_correct: boolean | null;
  exact_score_correct: boolean | null;
  brier: number | null;
  log_loss: number | null;
}

export interface CalibrationPoint {
  mean_predicted: number;
  empirical_freq: number;
  count: number;
}

export interface ModelRecord {
  evaluated_matches: number;
  winner_accuracy: number | null;
  winners_correct: number;
  exact_score_hits: number;
  avg_brier: number | null;
  avg_log_loss: number | null;
  calibration: CalibrationPoint[];
  best_calls: ModelRecordEntry[];
  biggest_misses: ModelRecordEntry[];
  last_updated: string | null;
  model_version: string;
  disclaimer: string;
}
