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

export interface TeamGoalBands {
  to_score: number;
  p2: number;
  p3: number;
  p4: number;
}

export interface GoalTotals {
  over_1_5: number;
  over_2_5: number;
  over_3_5: number;
}

export interface GoalMarkets {
  home: TeamGoalBands;
  away: TeamGoalBands;
  total: GoalTotals;
  btts: number;
}

export interface Goalscorer {
  name: string;
  position: string | null;
  p_score: number;
  p_score_2plus: number;
  xg: number;
}

/** Per-team likely scorers. `mode` is "squad" (pre-lineup estimate from the
 *  full squad) or "lineup" (sharpened on the announced XI). */
export interface Goalscorers {
  mode: "squad" | "lineup";
  home: Goalscorer[];
  away: Goalscorer[];
}

export interface AvailabilityPlayer {
  name: string;
  weight: number;
  status?: string | null;
  reason?: string | null;
}

export interface TeamAvailability {
  side: string;
  attack_delta_pct: number;
  players_out: AvailabilityPlayer[];
  note: string;
}

/** Announced-XI availability context (explanation only — does not move the
 *  published probabilities; the adjusted forecast is logged as a shadow twin). */
export interface Availability {
  has_lineup: boolean;
  per_team: TeamAvailability[];
}

/** One side's routes through a knockout tie. Unconditional probabilities —
 *  the three sum to that side's advance probability. */
export interface KnockoutPath {
  win_90: number;
  win_et: number;
  win_pens: number;
}

/** Knockout resolution block (model v0.5): who goes through, decomposed past
 *  the 90th minute. Only present for knockout fixtures. */
export interface KnockoutAdvance {
  p_advance_home: number;
  p_advance_away: number;
  /** Tie level after 90 — the regulation draw probability. */
  p_extra_time: number;
  /** Tie still level after 120. */
  p_shootout: number;
  paths: { home: KnockoutPath; away: KnockoutPath };
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
  /** Market consensus vs the model: margin-free implied probabilities from
   *  the latest pre-kickoff odds snapshot (median across bookmakers). */
  odds_comparison: {
    available: boolean;
    market?: Probabilities | null;
    captured_at?: string | null;
  };
  disclaimer: string;
  goal_markets: GoalMarkets | null;
  availability?: Availability | null;
  knockout?: KnockoutAdvance | null;
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

export interface GoalEvent {
  minute: number | null;
  side: "home" | "away";
  player: string;
  type: "goal" | "penalty" | "own_goal";
}

export interface CardEvent {
  minute: number | null;
  side: "home" | "away";
  player: string;
  type: "yellow" | "red";
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
  score_home_90?: number | null;
  score_away_90?: number | null;
  minute: number | null;
  period: LivePeriod;
  injury_time: number | null;
  penalty_home: number | null;
  penalty_away: number | null;
  goal_events: GoalEvent[];
  /** Bookings and sendings-off; optional so pre-cards payloads stay valid.
   *  A second yellow arrives as a single "red" event. */
  card_events?: CardEvent[];
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
  winner_accuracy_ci95: [number, number] | null;
  exact_score_rate: number | null;
  exact_score_ci95: [number, number] | null;
  winners_correct: number;
  exact_score_hits: number;
  best_streak: number;
  advancement_matches: number;
  advancement_correct: number;
  advancement_accuracy: number | null;
  advancement_ci95: [number, number] | null;
  avg_brier: number | null;
  avg_log_loss: number | null;
  calibration: CalibrationPoint[];
  best_calls: ModelRecordEntry[];
  biggest_misses: ModelRecordEntry[];
  last_updated: string | null;
  model_version: string;
  disclaimer: string;
}

// ---- Match lineups (display-only; never feeds the prediction model) ----
export interface LineupPlayer {
  name: string;
  number: number | null;
  position: string | null;
  grid: string | null;
  is_starter: boolean;
}

export interface TeamLineup {
  team: string;
  formation: string | null;
  coach: string | null;
  start_xi: LineupPlayer[];
  bench: LineupPlayer[];
}

export interface MatchLineups {
  available: boolean;
  message: string | null;
  home: TeamLineup | null;
  away: TeamLineup | null;
  fetched_at: string | null;
}

// ---- Official knockout bracket (live; real teams + scores, never picks) ----
export type KnockoutSide = {
  team_id: number | null;
  team: string | null;
  score: number | null;
  penalty: number | null;
};

export type KnockoutTie = {
  match_no: number;
  match_id: number | null;
  stage: "R32" | "R16" | "QF" | "SF" | "third_place" | "final";
  status: "scheduled" | "in_play" | "finished";
  kickoff_utc: string | null;
  home: KnockoutSide;
  away: KnockoutSide;
  minute: number | null;
  period: string | null;
  injury_time: number | null;
};

export type KnockoutBracket = { ties: KnockoutTie[] };

// ---- Model vs. market benchmark ----
export interface MarketBenchmark {
  status: string; // "pending" | "ready"
  dataset: string | null;
  n_matches: number;
  updated_at: string | null;
  model: { log_loss: number; brier: number; accuracy: number } | null;
  market: { log_loss: number; brier: number; accuracy: number } | null;
  diff_log_loss: number | null;
  diff_ci95: [number, number] | null;
  model_win_rate: number | null;
  mean_edge: number | null;
  verdict: string | null;
}
