/**
 * Tests for Task 27: Viewer UI personalisation, accessibility, and review page.
 * Requirements: 12.3–12.6, 12.9, 13.1, 14.1
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import { MetricHUD } from "@/components/MetricHUD";
import { OverlayCardView } from "@/components/OverlayCardView";
import { PersonalisationPanel } from "@/components/PersonalisationPanel";
import type { EventDot, MatchState, OverlayCard, ViewerProfile } from "@/lib/types";

// ── Helpers ──────────────────────────────────────────────────────────────────

function makeCard(overrides: Partial<OverlayCard> = {}): OverlayCard {
  return {
    card_id: "test-card-1",
    match_id: "m1",
    profile_key: "m1.sw.casual.neutral",
    match_clock: { period: 1, minute: 23, second: 10 },
    match_seconds: 1390,
    display_duration_ms: 5000,
    card_type: "stat",
    priority: 3,
    player_ref: null,
    team_ref: "Home",
    text: {
      sw: { headline: "Mpira umefika nusu ya uwanja", body: "Timu ya nyumbani inashikilia mpira." },
      en: { headline: "Ball reaches midfield", body: "Home team holds possession." },
    },
    gloss_en: {
      headline: "Ball reaches midfield",
      body: "Home team holds possession.",
    },
    structured_explanation: null,
    evidence_event_ids: [],
    stat_payload: {},
    audio_url: null,
    synthetic_ai_generated: true,
    from_bundle: false,
    ...overrides,
  };
}

const DEFAULT_PROFILE: ViewerProfile = {
  language: "sw",
  mode: "casual",
  club_perspective: "neutral",
  favourite_club: null,
  favourite_player: null,
  metric_focus: null,
  audio_enabled: true,
  audio_only: false,
};

// ── Gloss rendering ───────────────────────────────────────────────────────────

describe("OverlayCardView — gloss rendering (Req 12.4)", () => {
  it("renders gloss_en headline and body when language is sw and showGloss=true", () => {
    const card = makeCard();
    render(
      <OverlayCardView card={card} language="sw" showGloss={true} />
    );
    expect(screen.getByTestId("gloss-en")).toBeInTheDocument();
    expect(screen.getByTestId("gloss-headline")).toHaveTextContent(
      "Ball reaches midfield"
    );
    expect(screen.getByTestId("gloss-body")).toHaveTextContent(
      "Home team holds possession."
    );
  });

  it("does not render gloss when showGloss=false", () => {
    const card = makeCard();
    render(
      <OverlayCardView card={card} language="sw" showGloss={false} />
    );
    expect(screen.queryByTestId("gloss-en")).not.toBeInTheDocument();
  });

  it("does not render gloss when language is not sw", () => {
    const card = makeCard();
    render(
      <OverlayCardView card={card} language="en" showGloss={true} />
    );
    expect(screen.queryByTestId("gloss-en")).not.toBeInTheDocument();
  });

  it("does not render gloss when gloss_en is null", () => {
    const card = makeCard({ gloss_en: null });
    render(
      <OverlayCardView card={card} language="sw" showGloss={true} />
    );
    expect(screen.queryByTestId("gloss-en")).not.toBeInTheDocument();
  });
});

// ── AI / bundle labels ───────────────────────────────────────────────────────

describe("OverlayCardView — synthetic_ai_generated and from_bundle labels (Req 13.1)", () => {
  it("shows AI label when synthetic_ai_generated=true", () => {
    const card = makeCard({ synthetic_ai_generated: true });
    render(<OverlayCardView card={card} language="en" showGloss={false} />);
    expect(screen.getByTestId("ai-generated-label")).toBeInTheDocument();
  });

  it("hides AI label when synthetic_ai_generated=false", () => {
    const card = makeCard({ synthetic_ai_generated: false });
    render(<OverlayCardView card={card} language="en" showGloss={false} />);
    expect(screen.queryByTestId("ai-generated-label")).not.toBeInTheDocument();
  });

  it("shows BUNDLE label when from_bundle=true", () => {
    const card = makeCard({ from_bundle: true });
    render(<OverlayCardView card={card} language="en" showGloss={false} />);
    expect(screen.getByTestId("bundle-label")).toBeInTheDocument();
  });

  it("hides BUNDLE label when from_bundle=false", () => {
    const card = makeCard({ from_bundle: false });
    render(<OverlayCardView card={card} language="en" showGloss={false} />);
    expect(screen.queryByTestId("bundle-label")).not.toBeInTheDocument();
  });

  it("always renders the AI disclosure footer text", () => {
    const card = makeCard();
    render(<OverlayCardView card={card} language="en" showGloss={false} />);
    expect(screen.getByTestId("ai-disclosure")).toBeInTheDocument();
  });
});

// ── Keyboard navigation / ARIA ────────────────────────────────────────────────

describe("OverlayCardView — keyboard navigation (Req 14.1)", () => {
  it("thumb-up button is keyboard-focusable and has an accessible label", () => {
    const card = makeCard();
    render(<OverlayCardView card={card} language="en" showGloss={false} />);
    const btn = screen.getByTestId("thumb-up");
    expect(btn).toHaveAttribute("aria-label");
    btn.focus();
    expect(document.activeElement).toBe(btn);
  });

  it("thumb-down button is keyboard-focusable and has an accessible label", () => {
    const card = makeCard();
    render(<OverlayCardView card={card} language="en" showGloss={false} />);
    const btn = screen.getByTestId("thumb-down");
    expect(btn).toHaveAttribute("aria-label");
    btn.focus();
    expect(document.activeElement).toBe(btn);
  });

  it("edit button is shown for sw language and has aria-expanded", () => {
    const card = makeCard();
    render(<OverlayCardView card={card} language="sw" showGloss={true} />);
    const editBtn = screen.getByTestId("edit-button");
    expect(editBtn).toHaveAttribute("aria-expanded");
    expect(editBtn).toHaveAttribute("aria-label");
  });

  it("edit form opens when edit button is clicked via Enter key", () => {
    const card = makeCard();
    render(<OverlayCardView card={card} language="sw" showGloss={true} />);
    const editBtn = screen.getByTestId("edit-button");
    fireEvent.click(editBtn);
    expect(screen.getByRole("textbox")).toBeInTheDocument();
  });

  it("article has an accessible aria-label", () => {
    const card = makeCard();
    render(<OverlayCardView card={card} language="en" showGloss={false} />);
    const article = screen.getByTestId("overlay-card");
    expect(article).toHaveAttribute("aria-label");
  });
});

// ── Correction loop ───────────────────────────────────────────────────────────

describe("OverlayCardView — correction loop (Req 12.5)", () => {
  it("calls onThumbUp with card_id when thumb-up is clicked", () => {
    const onThumbUp = vi.fn();
    const card = makeCard({ card_id: "c-test" });
    render(
      <OverlayCardView
        card={card}
        language="en"
        showGloss={false}
        onThumbUp={onThumbUp}
      />
    );
    fireEvent.click(screen.getByTestId("thumb-up"));
    expect(onThumbUp).toHaveBeenCalledWith("c-test");
  });

  it("calls onThumbDown with card_id when thumb-down is clicked", () => {
    const onThumbDown = vi.fn();
    const card = makeCard({ card_id: "c-test" });
    render(
      <OverlayCardView
        card={card}
        language="en"
        showGloss={false}
        onThumbDown={onThumbDown}
      />
    );
    fireEvent.click(screen.getByTestId("thumb-down"));
    expect(onThumbDown).toHaveBeenCalledWith("c-test");
  });

  it("shows feedback confirmation after thumb-up", () => {
    const card = makeCard();
    render(<OverlayCardView card={card} language="en" showGloss={false} onThumbUp={vi.fn()} />);
    fireEvent.click(screen.getByTestId("thumb-up"));
    expect(screen.getByTestId("correction-submitted")).toBeInTheDocument();
  });

  it("calls onSubmitEdit with card_id and text on submit", () => {
    const onSubmitEdit = vi.fn();
    const card = makeCard({ card_id: "c-edit" });
    render(
      <OverlayCardView
        card={card}
        language="sw"
        showGloss={true}
        onSubmitEdit={onSubmitEdit}
      />
    );
    fireEvent.click(screen.getByTestId("edit-button"));
    const textarea = screen.getByRole("textbox");
    fireEvent.change(textarea, { target: { value: "Marekebisho ya maandishi" } });
    fireEvent.click(screen.getByRole("button", { name: /submit/i }));
    expect(onSubmitEdit).toHaveBeenCalledWith("c-edit", "Marekebisho ya maandishi");
  });
});

// ── PersonalisationPanel — profile_update messages ────────────────────────────

describe("PersonalisationPanel — profile update (Req 12.3)", () => {
  it("calls onChange with updated language when language radio is changed", () => {
    const onChange = vi.fn();
    render(
      <PersonalisationPanel
        profile={DEFAULT_PROFILE}
        homeTeam="Nyota FC"
        awayTeam="Jua United"
        onChange={onChange}
      />
    );
    fireEvent.click(screen.getByRole("radio", { name: /english/i }));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ language: "en" })
    );
  });

  it("calls onChange with updated mode when mode radio is changed", () => {
    const onChange = vi.fn();
    render(
      <PersonalisationPanel
        profile={DEFAULT_PROFILE}
        homeTeam="Nyota FC"
        awayTeam="Jua United"
        onChange={onChange}
      />
    );
    fireEvent.click(screen.getByRole("radio", { name: /analyst/i }));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ mode: "analyst" })
    );
  });

  it("calls onChange with audio_only=true when audio-only switch is toggled", () => {
    const onChange = vi.fn();
    render(
      <PersonalisationPanel
        profile={DEFAULT_PROFILE}
        homeTeam="Nyota FC"
        awayTeam="Jua United"
        onChange={onChange}
      />
    );
    fireEvent.click(screen.getByRole("switch", { name: /audio.only mode/i }));
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ audio_only: true })
    );
  });

  it("renders the audio-only switch as a role=switch element", () => {
    render(
      <PersonalisationPanel
        profile={DEFAULT_PROFILE}
        homeTeam="Nyota FC"
        awayTeam="Jua United"
        onChange={vi.fn()}
      />
    );
    expect(
      screen.getByRole("switch", { name: /audio.only mode/i })
    ).toBeInTheDocument();
  });
});

describe("MetricHUD — analyst team stats", () => {
  const state: MatchState = {
    match_id: "m1",
    minute: 31,
    second: 0,
    score_home: 0,
    score_away: 2,
    possession_home: 0.67,
    field_tilt_home: 0.67,
    field_tilt_away: 0.33,
    xg_home: 0,
    xg_away: 0.35,
    momentum_home: 45,
    momentum_away: 55,
    pressure_rate_home: 0,
    pressure_rate_away: 0,
    tempo: 1.2,
    team_home: "Nyota FC",
    team_away: "Jua United",
  };

  const events: EventDot[] = [
    {
      event_id: "e1",
      x: 90,
      y: 50,
      event_type: "goal",
      team: "Mombasa United",
      team_side: "away",
      player: "Asha Njeri",
      minute: 31,
      outcome: "goal",
    },
    {
      event_id: "e2",
      x: 20,
      y: 40,
      event_type: "pass",
      team: "Kisumu City",
      team_side: "home",
      player: "Amani Otieno",
      minute: 30,
      outcome: "success",
    },
  ];

  it("maps raw event team names to the displayed home/away sides", () => {
    render(<MetricHUD state={state} events={events} />);

    const rows = screen.getAllByRole("row").map((row) => row.textContent);
    expect(rows).toContain("Nyota FC0010");
    expect(rows).toContain("Jua United1100");
  });
});
