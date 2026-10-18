"use client";

import { useState } from "react";
import { cn, CARD_TYPE_LABEL, CARD_TYPE_COLOR, CARD_TYPE_BG } from "@/lib/utils";
import type { OverlayCard, Language } from "@/lib/types";

const CARD_ICON: Record<string, string> = {
  goal:            "⚽",
  key_moment:      "⚡",
  stat:            "📊",
  player_spotlight:"🌟",
  recap:           "🗂️",
};

interface Props {
  card: OverlayCard;
  language: Language;
  showGloss: boolean;
  onThumbUp?: (cardId: string) => void;
  onThumbDown?: (cardId: string) => void;
  onSubmitEdit?: (cardId: string, text: string) => void;
}

export function OverlayCardView({
  card,
  language,
  showGloss,
  onThumbUp,
  onThumbDown,
  onSubmitEdit,
}: Props) {
  const [editOpen, setEditOpen] = useState(false);
  const [editText, setEditText] = useState("");
  const [evidenceOpen, setEvidenceOpen] = useState(false);
  const [correctionSubmitted, setCorrectionSubmitted] = useState(false);

  const text = card.text[language] ?? card.text["en"] ?? { headline: "", body: "" };
  const colorCls = CARD_TYPE_COLOR[card.card_type] ?? "text-slate-400 border-slate-400/30";
  const bgCls = CARD_TYPE_BG[card.card_type] ?? "bg-slate-400/10";
  const icon = CARD_ICON[card.card_type] ?? "📌";
  const label = CARD_TYPE_LABEL[card.card_type] ?? card.card_type;

  const evidenceIds = card.evidence_event_ids ?? [];
  const explanation = card.structured_explanation;

  function handleSubmitEdit() {
    if (editText.trim()) {
      onSubmitEdit?.(card.card_id, editText.trim());
      setEditText("");
      setEditOpen(false);
      setCorrectionSubmitted(true);
    }
  }

  function handleThumbUp() {
    onThumbUp?.(card.card_id);
    setCorrectionSubmitted(true);
  }

  function handleThumbDown() {
    onThumbDown?.(card.card_id);
  }

  return (
    <article
      data-card-type={card.card_type}
      data-testid="overlay-card"
      className={cn(
        "animate-slide-up rounded-xl border p-4 flex flex-col gap-3",
        "bg-[--bg-elevated]",
        `border-[var(--card-accent,_#7C3AED)]/30`
      )}
      aria-label={`${label} overlay card`}
    >
      {/* ── Header ─────────────────────────────────────────────────── */}
      <header className="flex items-start justify-between gap-2">
        <div className="flex items-center gap-2 flex-wrap">
          <span
            className={cn(
              "inline-flex items-center gap-1 rounded-md px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wider",
              bgCls, colorCls.split(" ")[0]
            )}
            aria-hidden="true"
          >
            <span>{icon}</span>
            <span>{label}</span>
          </span>

          {/* synthetic_ai_generated label — always visible per requirement 13.1 */}
          {card.synthetic_ai_generated && (
            <span
              className="text-[9px] font-medium text-[--text-muted] border border-[--border-subtle]
                         rounded px-1.5 py-0.5"
              aria-label="AI generated content"
              data-testid="ai-generated-label"
            >
              AI
            </span>
          )}

          {/* from_bundle label — always visible per requirement 13.1 */}
          {card.from_bundle && (
            <span
              className="text-[9px] font-medium text-amber-400/70 border border-amber-400/20
                         rounded px-1.5 py-0.5"
              aria-label="Pre-generated bundle content"
              data-testid="bundle-label"
            >
              BUNDLE
            </span>
          )}
        </div>

        {/* Clock */}
        <span
          className="shrink-0 font-mono text-[11px] text-[--text-muted] tabular-nums"
          aria-label={`Match clock ${card.match_clock.minute} minutes ${card.match_clock.second} seconds`}
        >
          {card.match_clock.minute}&apos;{String(card.match_clock.second).padStart(2, "0")}
        </span>
      </header>

      {/* ── Primary text ────────────────────────────────────────────── */}
      <div className="flex flex-col gap-1">
        <h2 className="text-sm font-bold leading-snug text-[--text-primary]">
          {text.headline}
        </h2>
        <p className="text-xs leading-relaxed text-[--text-secondary]">
          {text.body}
        </p>

        {/* Swahili gloss — rendered directly beneath per requirement 12.4 */}
        {showGloss && language === "sw" && (
          (() => {
            const englishText = card.gloss_en
              ? { headline: card.gloss_en.headline, body: card.gloss_en.body }
              : null;
            if (!englishText) return null;
            return (
              <div
                className="mt-1 pl-2 border-l-2 border-[--border-muted]"
                aria-label="English translation"
                data-testid="gloss-en"
              >
                <p className="text-[11px] italic text-[--text-muted]" data-testid="gloss-headline">
                  {englishText.headline}
                </p>
                <p className="text-[11px] text-[--text-muted]" data-testid="gloss-body">
                  {englishText.body}
                </p>
              </div>
            );
          })()
        )}
      </div>

      {/* ── Explainability / Evidence ────────────────────────────────── */}
      {explanation && (
        <div className="flex flex-col gap-1">
          <p className="text-[11px] text-[--text-secondary] leading-relaxed">
            <span className="font-medium text-[--text-muted] uppercase text-[9px] tracking-wider mr-1">
              Reason:
            </span>
            {explanation.reason}
          </p>

          {evidenceIds.length > 0 && (
            <div className="flex flex-wrap gap-1 items-center">
              <span className="text-[9px] uppercase tracking-wider text-[--text-muted]">
                Evidence:
              </span>
              {evidenceIds.map((id) => (
                <button
                  key={id}
                  onClick={() => setEvidenceOpen((v) => !v)}
                  className="text-[10px] font-mono text-[--text-muted] border border-[--border-subtle]
                             rounded px-1.5 py-px hover:border-[--border-default] transition-colors
                             focus-visible:ring-2 focus-visible:ring-violet-500"
                  aria-expanded={evidenceOpen}
                  aria-label={`Event evidence ${id} — click to expand`}
                >
                  {id}
                </button>
              ))}
            </div>
          )}

          {/* Evidence popover */}
          {evidenceOpen && explanation.numeric_evidence.length > 0 && (
            <div
              className="mt-1 rounded-lg bg-[--bg-inset] border border-[--border-subtle] p-2 flex flex-col gap-1"
              role="region"
              aria-label="Evidence details"
            >
              {explanation.numeric_evidence.map((ev) => (
                <div key={ev.metric} className="flex items-center justify-between text-[10px]">
                  <span className="text-[--text-muted] uppercase tracking-wider">{ev.metric}</span>
                  <span className="font-mono text-[--text-secondary] tabular-nums">{ev.display_value}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      )}

      {/* ── Footer: AI label + correction loop ───────────────────────── */}
      <footer className="flex flex-col gap-2 pt-1 border-t border-[--border-subtle]">
        {/* Responsible AI disclosure — always visible */}
        <p
          className="text-[9px] text-[--text-muted] font-medium uppercase tracking-wider"
          aria-label="Content disclosure: synthetic and AI generated"
          data-testid="ai-disclosure"
        >
          ⚙ synthetic · ai-generated
        </p>

        {/* Correction loop */}
        {!correctionSubmitted ? (
          <div className="flex items-center gap-1" role="group" aria-label="Rate this narration">
            <button
              onClick={handleThumbUp}
              className="flex items-center justify-center w-8 h-8 text-base
                         text-[--text-muted] hover:text-emerald-400 transition-colors
                         rounded-md border border-transparent hover:border-emerald-400/30
                         focus-visible:ring-2 focus-visible:ring-violet-500"
              aria-label="Rate this narration as accurate"
              data-testid="thumb-up"
              type="button"
            >
              👍
            </button>
            <button
              onClick={handleThumbDown}
              className="flex items-center justify-center w-8 h-8 text-base
                         text-[--text-muted] hover:text-red-400 transition-colors
                         rounded-md border border-transparent hover:border-red-400/30
                         focus-visible:ring-2 focus-visible:ring-violet-500"
              aria-label="Rate this narration as inaccurate"
              data-testid="thumb-down"
              type="button"
            >
              👎
            </button>

            {language === "sw" && (
              <button
                onClick={() => setEditOpen((v) => !v)}
                className="ml-auto text-[11px] text-[--text-muted] hover:text-violet-400
                           transition-colors px-2 py-1 rounded-md border border-[--border-subtle]
                           hover:border-violet-400/40 focus-visible:ring-2 focus-visible:ring-violet-500"
                aria-expanded={editOpen}
                aria-label="Suggest a correction to the Swahili narration"
                data-testid="edit-button"
              >
                ✏ Edit
              </button>
            )}
          </div>
        ) : (
          <p
            className="text-[10px] text-emerald-400"
            role="status"
            aria-live="polite"
            data-testid="correction-submitted"
          >
            ✓ Feedback recorded
          </p>
        )}

        {editOpen && !correctionSubmitted && (
          <div className="flex flex-col gap-2" role="group" aria-label="Correction form">
            <label
              htmlFor={`edit-${card.card_id}`}
              className="text-[9px] uppercase tracking-widest text-[--text-muted]"
            >
              Suggest correction in Swahili
            </label>
            <textarea
              id={`edit-${card.card_id}`}
              value={editText}
              onChange={(e) => setEditText(e.target.value)}
              placeholder="Suggest a correction in Swahili…"
              rows={3}
              className="w-full resize-none rounded-md bg-[--bg-inset] border border-[--border-muted]
                         text-[11px] text-[--text-primary] placeholder-[--text-muted] p-2
                         focus:outline-none focus:border-violet-500/60 focus:ring-2 focus:ring-violet-500/30"
              aria-label="Swahili correction text"
            />
            <div className="flex gap-2 justify-end">
              <button
                onClick={() => setEditOpen(false)}
                className="text-[11px] text-[--text-muted] hover:text-[--text-primary] px-3 py-1
                           rounded-md border border-[--border-subtle] transition-colors
                           focus-visible:ring-2 focus-visible:ring-violet-500"
              >
                Cancel
              </button>
              <button
                onClick={handleSubmitEdit}
                disabled={!editText.trim()}
                className="text-[11px] text-[--text-inverse] bg-violet-600 hover:bg-violet-500
                           disabled:opacity-40 disabled:cursor-not-allowed px-3 py-1 rounded-md
                           transition-colors focus-visible:ring-2 focus-visible:ring-violet-500"
                aria-disabled={!editText.trim()}
              >
                Submit
              </button>
            </div>
          </div>
        )}
      </footer>
    </article>
  );
}
