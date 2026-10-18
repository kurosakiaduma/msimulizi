"use client";

import { useEffect, useRef } from "react";
import type { OverlayCard, Language, ScheduledCard } from "@/lib/types";
import { OverlayCardView } from "./OverlayCardView";

interface Props {
  current: ScheduledCard | null;
  history: OverlayCard[];
  language: Language;
  hasStarted: boolean;
  onThumbUp?: (cardId: string) => void;
  onThumbDown?: (cardId: string) => void;
  onSubmitEdit?: (cardId: string, text: string) => void;
}

export function CardFeed({
  current,
  history,
  language,
  hasStarted,
  onThumbUp,
  onThumbDown,
  onSubmitEdit,
}: Props) {
  const feedRef = useRef<HTMLDivElement>(null);

  // Auto-scroll to top when a new card arrives
  useEffect(() => {
    if (feedRef.current) {
      feedRef.current.scrollTop = 0;
    }
  }, [current?.card_id]);

  const showGloss = language === "sw";

  return (
    <section
      aria-label="Live commentary feed"
      className="flex flex-col gap-3 h-full overflow-y-auto"
      ref={feedRef}
    >
      {/* Current (live) card at top */}
      {current && (
        <div key={current.card_id} className="relative">
          {/* Live indicator */}
          <div className="absolute -top-1 -right-1 z-10">
            <span
              className="animate-pulse-live inline-flex items-center gap-1 rounded-full
                         bg-red-500/20 border border-red-500/40 px-1.5 py-px text-[9px]
                         font-semibold uppercase tracking-wider text-red-400"
              aria-label="Live card"
            >
              <span className="h-1.5 w-1.5 rounded-full bg-red-500 animate-pulse-live" />
              LIVE
            </span>
          </div>
          <OverlayCardView
            card={current}
            language={language}
            showGloss={showGloss}
            onThumbUp={onThumbUp}
            onThumbDown={onThumbDown}
            onSubmitEdit={onSubmitEdit}
          />
        </div>
      )}

      {/* History */}
      {history.length > 0 && (
        <div className="flex flex-col gap-2 opacity-70">
          <span className="text-[9px] uppercase tracking-widest text-[--text-muted] px-1">
            Earlier
          </span>
          {[...history].reverse().slice(0, 20).map((card) => (
            <OverlayCardView
              key={card.card_id}
              card={card}
              language={language}
              showGloss={showGloss}
              onThumbUp={onThumbUp}
              onThumbDown={onThumbDown}
              onSubmitEdit={onSubmitEdit}
            />
          ))}
        </div>
      )}

      {!current && history.length === 0 && (
        <div className="flex flex-col items-center justify-center h-32 text-[--text-muted] text-xs gap-2">
          <span className="text-2xl">📡</span>
          <span>{hasStarted ? "Match in progress…" : "Select a storyline and press Start"}</span>
        </div>
      )}
    </section>
  );
}
