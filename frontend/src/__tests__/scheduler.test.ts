/**
 * Unit tests for the client-side card priority scheduler.
 * Requirements: 8.5, 12.7
 */

import { describe, it, expect } from "vitest";
import {
  createSchedulerState,
  enqueueCard,
  tick,
  isStale,
} from "@/lib/scheduler";
import type { OverlayCard } from "@/lib/types";

function makeCard(overrides: Partial<OverlayCard> = {}): OverlayCard {
  return {
    card_id: "c1",
    match_id: "m1",
    profile_key: "m1.en.casual.neutral",
    match_clock: { period: 1, minute: 10, second: 0 },
    match_seconds: 600,
    display_duration_ms: 5000,
    card_type: "stat",
    priority: 3,
    player_ref: null,
    team_ref: "Home",
    text: { en: { headline: "Stat headline", body: "Stat body" } },
    gloss_en: null,
    structured_explanation: null,
    evidence_event_ids: [],
    stat_payload: {},
    audio_url: null,
    synthetic_ai_generated: true,
    from_bundle: false,
    ...overrides,
  };
}

const ANCHOR_WALL  = 1_000_000;
const ANCHOR_MATCH = 600;
const SPEED        = 1;

describe("Scheduler — enqueueCard", () => {
  it("shows a card immediately when slot is empty", () => {
    const s0 = createSchedulerState();
    const s1 = enqueueCard(s0, makeCard({ card_id: "c1" }), ANCHOR_WALL, ANCHOR_MATCH, SPEED, ANCHOR_WALL);
    expect(s1.current?.card_id).toBe("c1");
  });

  it("pre-empts the current card when a higher-priority card arrives", () => {
    const s0 = createSchedulerState();
    const low  = makeCard({ card_id: "low",  priority: 3 });
    const high = makeCard({ card_id: "high", priority: 2 });
    const now = ANCHOR_WALL;

    const s1 = enqueueCard(s0,  low,  ANCHOR_WALL, ANCHOR_MATCH, SPEED, now);
    const s2 = enqueueCard(s1,  high, ANCHOR_WALL, ANCHOR_MATCH, SPEED, now);

    expect(s2.current?.card_id).toBe("high");
  });

  it("does NOT pre-empt a lower-rank-number card with a higher-rank-number card", () => {
    const s0 = createSchedulerState();
    const high = makeCard({ card_id: "high", priority: 2 });
    const low  = makeCard({ card_id: "low",  priority: 4 });
    const now = ANCHOR_WALL;

    const s1 = enqueueCard(s0, high, ANCHOR_WALL, ANCHOR_MATCH, SPEED, now);
    const s2 = enqueueCard(s1, low,  ANCHOR_WALL, ANCHOR_MATCH, SPEED, now);

    expect(s2.current?.card_id).toBe("high");
  });

  it("queues Priority Rank 1 cards rather than dropping them", () => {
    const s0 = createSchedulerState();
    const rank1_a = makeCard({ card_id: "r1a", priority: 1 });
    const rank1_b = makeCard({ card_id: "r1b", priority: 1 });
    const now = ANCHOR_WALL;

    const s1 = enqueueCard(s0, rank1_a, ANCHOR_WALL, ANCHOR_MATCH, SPEED, now);
    const s2 = enqueueCard(s1, rank1_b, ANCHOR_WALL, ANCHOR_MATCH, SPEED, now);

    // Both are in the rank-1 queue; slot was empty so first card became current
    expect(s1.current?.card_id).toBe("r1a");
    expect(s2.rank1Queue.length).toBe(1);
    expect(s2.rank1Queue[0].card_id).toBe("r1b");
  });

  it("drops stale non-Priority-Rank-1 cards", () => {
    const s0 = createSchedulerState();
    const card = makeCard({ card_id: "stale", priority: 3, match_seconds: 0 });
    // "now" is far in the future relative to anchor
    const farFuture = ANCHOR_WALL + 1_000_000;

    const s1 = enqueueCard(s0, card, ANCHOR_WALL, ANCHOR_MATCH, SPEED, farFuture);
    expect(s1.current).toBeNull();
  });

  it("does NOT drop stale Priority Rank 1 cards", () => {
    const s0 = createSchedulerState();
    const card = makeCard({ card_id: "r1stale", priority: 1, match_seconds: 0 });
    const farFuture = ANCHOR_WALL + 1_000_000;

    const s1 = enqueueCard(s0, card, ANCHOR_WALL, ANCHOR_MATCH, SPEED, farFuture);
    // Rank-1 always shown (fills current when slot empty, even if stale)
    expect(s1.current?.card_id).toBe("r1stale");
  });
});

describe("Scheduler — tick", () => {
  it("retires the current card when its window expires", () => {
    const s0 = createSchedulerState();
    const card = makeCard({ card_id: "c1", display_duration_ms: 100 });
    const now = ANCHOR_WALL;
    const s1 = enqueueCard(s0, card, ANCHOR_WALL, ANCHOR_MATCH, SPEED, now);
    expect(s1.current).not.toBeNull();

    // Tick after window ends
    const s2 = tick(s1, now + 200);
    expect(s2.current).toBeNull();
  });

  it("promotes the next rank-1 card when current slot expires", () => {
    const s0 = createSchedulerState();
    const first  = makeCard({ card_id: "first",  priority: 1, display_duration_ms: 100 });
    const second = makeCard({ card_id: "second", priority: 1, display_duration_ms: 5000 });
    const now = ANCHOR_WALL;

    let s = enqueueCard(s0,    first,  ANCHOR_WALL, ANCHOR_MATCH, SPEED, now);
    s     = enqueueCard(s,     second, ANCHOR_WALL, ANCHOR_MATCH, SPEED, now);

    expect(s.current?.card_id).toBe("first");
    expect(s.rank1Queue.length).toBe(1);

    // Expire first card
    s = tick(s, now + 200);
    expect(s.current?.card_id).toBe("second");
    expect(s.rank1Queue.length).toBe(0);
  });
});

describe("Scheduler — late arrival", () => {
  it("shows a late card immediately (display_from_wall in the past)", () => {
    const s0 = createSchedulerState();
    // Card match_seconds < anchor_match → display_from_wall in the past
    const lateCard = makeCard({ card_id: "late", match_seconds: 0, priority: 3 });
    const now = ANCHOR_WALL + 10_000;  // 10s after anchor

    const s1 = enqueueCard(s0, lateCard, ANCHOR_WALL, ANCHOR_MATCH, SPEED, now);
    // display_from_wall = ANCHOR_WALL + (0 - 600) / 1 * 1000 = ANCHOR_WALL - 600_000
    // That's in the past but stale check uses duration window:
    // endsAt = display_from_wall + 5000 = ANCHOR_WALL - 595_000 < now → stale → DROPPED for non-rank-1
    // So this tests the stale path: card is dropped
    // For a card that is "late" but NOT stale:
    const nearLate = makeCard({ card_id: "nearlate", match_seconds: ANCHOR_MATCH - 1, priority: 3 });
    // display_from_wall = ANCHOR_WALL + (-1/1)*1000 = ANCHOR_WALL - 1000
    // endsAt = ANCHOR_WALL - 1000 + 5000 = ANCHOR_WALL + 4000
    // If now = ANCHOR_WALL + 2000 → not stale → shown
    const s2 = enqueueCard(s0, nearLate, ANCHOR_WALL, ANCHOR_MATCH, SPEED, ANCHOR_WALL + 2000);
    expect(s2.current?.card_id).toBe("nearlate");
  });
});

describe("Scheduler — speed changes", () => {
  it("scales display_from_wall correctly at 2x speed", () => {
    const s0 = createSchedulerState();
    const card = makeCard({ card_id: "c1", match_seconds: 620 }); // 20s ahead of anchor
    const now  = ANCHOR_WALL;
    const s1   = enqueueCard(s0, card, ANCHOR_WALL, ANCHOR_MATCH, 2, now);

    // display_from_wall = ANCHOR_WALL + (620-600)/2 * 1000 = ANCHOR_WALL + 10_000
    expect(s1.current?.display_from_wall).toBeCloseTo(ANCHOR_WALL + 10_000, 0);
  });

  it("scales display_from_wall correctly at 0.1x speed", () => {
    const s0 = createSchedulerState();
    const card = makeCard({ card_id: "c1", match_seconds: 610 }); // 10s ahead of anchor
    const now  = ANCHOR_WALL;
    const s1   = enqueueCard(s0, card, ANCHOR_WALL, ANCHOR_MATCH, 0.1, now);

    // display_from_wall = ANCHOR_WALL + 10/0.1 * 1000 = ANCHOR_WALL + 100_000
    expect(s1.current?.display_from_wall).toBeCloseTo(ANCHOR_WALL + 100_000, 0);
  });
});

describe("isStale", () => {
  it("returns true when display window has passed", () => {
    const card = { display_from_wall: 1000, display_duration_ms: 500 } as ReturnType<typeof makeCard> & { display_from_wall: number };
    expect(isStale(card as Parameters<typeof isStale>[0], 2000)).toBe(true);
  });

  it("returns false when display window is still active", () => {
    const card = { display_from_wall: 1000, display_duration_ms: 5000 } as ReturnType<typeof makeCard> & { display_from_wall: number };
    expect(isStale(card as Parameters<typeof isStale>[0], 2000)).toBe(false);
  });
});
