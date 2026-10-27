"use client";

import { useState } from "react";

export const STORYLINES = [
  { id: "comeback_from_two_down", label: "Comeback from 2–0" },
  { id: "red_card_shift", label: "Red Card Shift" },
  { id: "late_equaliser", label: "Late Equaliser" },
  { id: "dominant_side_loses", label: "Dominant Side Loses" },
];

export const REPLAY_SPEEDS = [1, 10, 30, 60] as const;

interface Props {
  selectedStoryline: string;
  isConnected: boolean;
  hasStarted: boolean;
  isFinished: boolean;
  speed: number;
  onSelectStoryline: (id: string) => void;
  onSelectSpeed: (speed: number) => void;
  onStart: () => void;
}

export function ReplayPanel({
  selectedStoryline,
  isConnected,
  hasStarted,
  isFinished,
  speed,
  onSelectStoryline,
  onSelectSpeed,
  onStart,
}: Props) {
  const [open, setOpen] = useState(false);

  const currentLabel =
    STORYLINES.find((s) => s.id === selectedStoryline)?.label ?? "Select storyline";

  return (
    <section
      aria-label="Replay controls"
      className="flex flex-col gap-3 p-4 rounded-xl bg-[--bg-elevated] border border-[--border-subtle]"
    >
      <div className="flex items-center justify-between">
        <h2 className="text-[10px] font-bold uppercase tracking-widest text-[--text-muted]">
          Replay Controls
        </h2>
        <div className="flex items-center gap-1.5">
          <span
            className={`h-1.5 w-1.5 rounded-full ${isConnected ? "bg-emerald-400" : "bg-red-400"}`}
            aria-hidden="true"
          />
          <span className="text-[9px] text-[--text-muted]">
            {isConnected ? "Connected" : "Disconnected"}
          </span>
        </div>
      </div>

      {/* Storyline selector — disabled while match is running */}
      <div className="relative">
        <button
          onClick={() => !hasStarted && setOpen((v) => !v)}
          disabled={hasStarted && !isFinished}
          className="w-full flex items-center justify-between rounded-lg bg-[--bg-inset]
                     border border-[--border-subtle] px-3 py-2 text-xs text-[--text-secondary]
                     hover:border-[--border-default] transition-colors
                     disabled:opacity-50 disabled:cursor-not-allowed"
          aria-haspopup="listbox"
          aria-expanded={open}
          aria-label={`Selected storyline: ${currentLabel}`}
        >
          <span className="truncate">{currentLabel}</span>
          <span className="text-[--text-muted] ml-2" aria-hidden="true">▾</span>
        </button>

        {open && (
          <ul
            role="listbox"
            aria-label="Storyline options"
            className="absolute left-0 right-0 top-full mt-1 z-20 rounded-lg overflow-hidden
                       border border-[--border-default] shadow-xl"
            style={{ background: "#161b28" }}
          >
            {STORYLINES.map((s) => (
              <li
                key={s.id}
                role="option"
                aria-selected={s.id === selectedStoryline}
                onClick={() => { onSelectStoryline(s.id); setOpen(false); }}
                className={`px-3 py-2 text-xs cursor-pointer transition-colors
                            ${s.id === selectedStoryline
                    ? "bg-violet-600/20 text-violet-300"
                    : "text-[--text-secondary] hover:bg-white/5"
                  }`}
              >
                {s.label}
              </li>
            ))}
          </ul>
        )}
      </div>

      {/* Replay speed — fixed at session start because the adapter is paced
          when the session is created. A faster replay makes a short demo
          possible without waiting the full 90 match minutes. */}
      <div className="flex flex-col gap-1.5">
        <label
          htmlFor="replay-speed"
          className="text-[9px] font-semibold uppercase tracking-widest text-[--text-muted]"
        >
          Replay speed
        </label>
        <select
          id="replay-speed"
          aria-label="Replay speed"
          value={speed}
          onChange={(event) => onSelectSpeed(Number(event.target.value))}
          disabled={hasStarted && !isFinished}
          className="w-full rounded-lg bg-[--bg-inset] border border-[--border-subtle]
                     px-3 py-2 text-xs text-[--text-secondary]
                     hover:border-[--border-default] transition-colors
                     disabled:opacity-50 disabled:cursor-not-allowed"
        >
          {REPLAY_SPEEDS.map((value) => (
            <option key={value} value={value}>
              {value}× {value === 1 ? "(live pace)" : ""}
            </option>
          ))}
        </select>
        <p className="text-[9px] leading-relaxed text-[--text-muted]">
          Set before Start. 30× reaches the first key moment in about 24 seconds.
        </p>
      </div>

      {/* Start / Restart button */}
      <button
        onClick={onStart}
        className={`w-full rounded-lg px-4 py-2 text-xs font-semibold transition-colors
                    flex items-center justify-center gap-2
                    ${hasStarted
            ? "bg-[--bg-inset] border border-[--border-subtle] text-[--text-secondary] hover:bg-white/5 hover:border-[--border-default]"
            : "bg-violet-600 border border-violet-500 text-white hover:bg-violet-500"
          }`}
        aria-label={hasStarted ? "Restart replay from the beginning" : "Start replay"}
      >
        <span aria-hidden="true">{hasStarted ? "↺" : "▶"}</span>
        {hasStarted ? "Restart" : "Start"}
      </button>
    </section>
  );
}
