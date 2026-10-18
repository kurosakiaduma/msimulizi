/* ──────────────────────────────────────────────────────────
   Msimulizi frontend types
   Mirror of shared/models.py — keep in sync with backend.
────────────────────────────────────────────────────────── */

export type Language = "sw" | "en" | "fr";
export type Mode = "analyst" | "casual";
export type ClubPerspective = "home" | "away" | "neutral";
export type CardType = "goal" | "key_moment" | "stat" | "player_spotlight" | "recap";

export interface MatchClock {
  period: 1 | 2;
  minute: number;
  second: number;
}

export interface TextContent {
  headline: string;
  body: string;
}

export interface GlossEn {
  headline: string;
  body: string;
}

export interface NumericEvidence {
  metric: string;
  raw_value: number;
  display_value: string;
  unit: string;
}

export interface StructuredExplanation {
  theme: string;
  reason: string;
  numeric_evidence: NumericEvidence[];
  evidence_event_ids: string[];
  partially_grounded: boolean;
}

export interface OverlayCard {
  card_id: string;
  match_id: string;
  profile_key: string;
  match_clock: MatchClock;
  match_seconds: number;
  display_duration_ms: number;
  card_type: CardType;
  priority: number;           // 1 = highest
  player_ref: string | null;
  team_ref: string;
  text: Partial<Record<Language, TextContent>>;
  gloss_en: GlossEn | null;
  structured_explanation: StructuredExplanation | null;
  evidence_event_ids: string[];
  stat_payload: Record<string, unknown>;
  audio_url: string | null;
  synthetic_ai_generated: boolean;
  from_bundle: boolean;
}

export interface EventDot {
  event_id: string;
  x: number;           // 0–100 pitch coordinate
  y: number;
  event_type: string;
  team: string;
  player: string;
  minute: number;
  outcome: string | null;
}

export interface MatchState {
  match_id: string;
  minute: number;
  second: number;
  score_home: number;
  score_away: number;
  possession_home: number;     // 0–1
  field_tilt_home: number;
  field_tilt_away: number;
  xg_home: number;
  xg_away: number;
  momentum_home: number;       // 0–100
  momentum_away: number;
  pressure_rate_home: number;
  pressure_rate_away: number;
  tempo: number;
  team_home: string;
  team_away: string;
}

export interface ClockUpdate {
  type: "clock_update";
  match_seconds: number;
  speed: number;
  anchor: number;              // wall-clock epoch ms when anchor was set
}

export interface AudioUpdate {
  type: "audio_update";
  card_id: string;
  audio_url: string;
  match_seconds: number;
}

export type WsMessage =
  | { type: "card";          card: OverlayCard; match_id: string }
  | { type: "clock_update";  clock: {
      match_seconds?: number; speed?: number;
      minute?: number; second?: number;
      score_home?: number; score_away?: number;
      momentum_home?: number; momentum_away?: number;
      possession_home?: number;
      xg_home?: number; xg_away?: number;
      field_tilt_home?: number; field_tilt_away?: number;
      tempo?: number;
      // event-dot fields (event dots are broadcast via clock_update channel)
      type?: string; event_id?: string; x?: number; y?: number;
      event_type?: string; team?: string; player?: string;
      minute_val?: number; outcome?: string | null;
    }
  }
  | AudioUpdate
  | { type: "state_update";  payload: MatchState }
  | { type: "event";         payload: EventDot }
  | { type: "score_update";  home: number; away: number; minute: number }
  | { type: "full_time";     session_id: string; match_id: string; cards_emitted: number }
  | { type: "welcome";       session_id: string }
  | { type: "ping" }
  | { type: "pong" }
  | { type: "ack";           cmd: string };

/* Viewer profile */
export interface ViewerProfile {
  language: Language;
  mode: Mode;
  club_perspective: ClubPerspective;
  favourite_club: string | null;
  favourite_player: string | null;
  metric_focus: string | null;
  audio_enabled: boolean;
  audio_only: boolean;
}

/* Scheduler queue item */
export interface ScheduledCard extends OverlayCard {
  display_from_wall: number;   // computed wall-clock ms for display start
}

/* Storyline selector */
export interface Storyline {
  id: string;
  label: string;
}
