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
  /** wall-clock ms when current card's display window ends */
  currentEndsAt: number;
}

export function createSchedulerState(): SchedulerState {
  return { current: null, rank1Queue: [], currentEndsAt: 0 };
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
  if (state.current !== null && nowMs >= state.currentEndsAt) {
    // Retire current
    const [next, ...rest] = state.rank1Queue;
    if (next) {
      // Late arrival: show immediately
      const displayFrom = Math.min(next.display_from_wall, nowMs);
      return {
        current: { ...next, display_from_wall: displayFrom },
        rank1Queue: rest,
        currentEndsAt: displayFrom + next.display_duration_ms,
      };
    }
    return { current: null, rank1Queue: [], currentEndsAt: 0 };
  }
  return state;
}
