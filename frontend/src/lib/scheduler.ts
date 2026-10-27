/**
 * Client-side card priority scheduler.
 *
 * Rules (from Requirement 8.5):
 *   - One card displayed at a time.
 *   - A higher-priority (lower rank number) card pre-empts the current card.
 *   - Priority Rank 1 cards are queued rather than dropped.
 *   - Stale lower-priority cards are dropped (display window already passed).
 *   - Late cards (display_from_wall in the past) are shown immediately.
 */

import type { OverlayCard, ScheduledCard } from "./types";
export type { ScheduledCard } from "./types";

export interface SchedulerState {
  current: ScheduledCard | null;
  rank1Queue: ScheduledCard[];
  /** Cards received before their match timestamp is reached. */
  pending: ScheduledCard[];
  /** wall-clock ms when current card's display window ends */
  currentEndsAt: number;
}

export function createSchedulerState(): SchedulerState {
  return { current: null, rank1Queue: [], pending: [], currentEndsAt: 0 };
}

/**
 * Compute wall-clock display_from_wall for a card given the current clock anchor.
 *
 * anchor_wall: wall-clock epoch ms when anchor was set
 * anchor_match: match_seconds at that anchor
 * speed: replay speed multiplier
 */
export function computeDisplayFrom(
  card: OverlayCard,
  anchorWall: number,
  anchorMatch: number,
  speed: number
): number {
  if (speed <= 0) return Date.now();
  const offsetMatchSeconds = card.match_seconds - anchorMatch;
  const offsetWallMs = (offsetMatchSeconds / speed) * 1000;
  return anchorWall + offsetWallMs;
}

/**
 * Attach a late-arriving audio URL to any queued/visible copy of a card.
 *
 * Audio is synthesized after the caption, so `audio_update` normally arrives
 * after the card has been shown. Updating every scheduler slot keeps the
 * audio-only player and the card view in sync.
 */
export function applyAudioUrl(
  state: SchedulerState,
  cardId: string,
  audioUrl: string | null
): SchedulerState {
  const patch = <T extends ScheduledCard>(card: T): T =>
    card.card_id === cardId ? { ...card, audio_url: audioUrl } : card;

  return {
    ...state,
    current: state.current ? patch(state.current) : null,
    rank1Queue: state.rank1Queue.map(patch),
    pending: state.pending.map(patch),
  };
}

/** Returns true if a card's display window has already passed (stale). */
export function isStale(card: ScheduledCard, nowMs: number): boolean {
  const endsAt = card.display_from_wall + card.display_duration_ms;
  return endsAt < nowMs;
}

/**
 * Attempt to enqueue a new card.
 * Returns the mutated state (caller should spread to trigger re-render).
 */
export function enqueueCard(
  state: SchedulerState,
  card: OverlayCard,
  anchorWall: number,
  anchorMatch: number,
  speed: number,
  nowMs: number = Date.now()
): SchedulerState {
  const scheduled: ScheduledCard = {
    ...card,
    display_from_wall: computeDisplayFrom(card, anchorWall, anchorMatch, speed),
  };

  if (scheduled.display_from_wall > nowMs) {
    return {
      ...state,
      pending: [...state.pending, scheduled].sort(
        (a, b) => a.display_from_wall - b.display_from_wall
      ),
    };
  }

  // Drop stale lower-priority cards immediately
  if (card.priority > 1 && isStale(scheduled, nowMs)) {
    return state;
  }

  // Priority Rank 1 — fill the slot if empty, otherwise queue (never drop)
  if (card.priority === 1) {
    if (state.current === null) {
      return {
        ...state,
        current: scheduled,
        currentEndsAt: scheduled.display_from_wall + scheduled.display_duration_ms,
      };
    }
    return {
      ...state,
      rank1Queue: [...state.rank1Queue, scheduled],
    };
  }

  // Pre-empt current card if new card has higher priority (lower number)
  if (
    state.current !== null &&
    card.priority < state.current.priority &&
    state.current.priority > 1
  ) {
    // Replace current; stale check already done above for non-rank-1
    return {
      ...state,
      current: scheduled,
      currentEndsAt: scheduled.display_from_wall + scheduled.display_duration_ms,
    };
  }

  // No current card — show immediately
  if (state.current === null) {
    return {
      ...state,
      current: scheduled,
      currentEndsAt: scheduled.display_from_wall + scheduled.display_duration_ms,
    };
  }

  // Otherwise drop (lower priority, slot occupied)
  return state;
}

/**
 * Called on each tick: retire the current card if its window has passed,
 * then promote from rank-1 queue if available.
 */
export function tick(
  state: SchedulerState,
  nowMs: number = Date.now()
): SchedulerState {
  const due = state.pending.filter((card) => card.display_from_wall <= nowMs);
  const pending = state.pending.filter((card) => card.display_from_wall > nowMs);

  if (state.current === null && due.length > 0) {
    const [next, ...rest] = due;
    return {
      ...state,
      current: next,
      pending,
      rank1Queue: [...state.rank1Queue, ...rest],
      currentEndsAt: next.display_from_wall + next.display_duration_ms,
    };
  }

  if (state.current !== null && nowMs >= state.currentEndsAt) {
    // Retire current
    const [next, ...rest] = [...state.rank1Queue, ...due];
    if (next) {
      // Late arrival: show immediately
      const displayFrom = Math.min(next.display_from_wall, nowMs);
      return {
        current: { ...next, display_from_wall: displayFrom },
        rank1Queue: rest,
        pending,
        currentEndsAt: displayFrom + next.display_duration_ms,
      };
    }
    return { current: null, rank1Queue: [], pending, currentEndsAt: 0 };
  }
  return pending.length === state.pending.length ? state : { ...state, pending };
}
