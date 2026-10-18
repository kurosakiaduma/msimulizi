"use client";

import { formatClock } from "@/lib/utils";

interface Props {
  minute: number;
  second: number;
  period: 1 | 2;
  isLive: boolean;
}

export function MatchClock({ minute, second, period, isLive }: Props) {
  return (
    <div
      className="flex items-center gap-2 select-none"
      aria-label={`Match clock: ${minute} minutes ${second} seconds, period ${period}`}
    >
      {isLive && (
        <span
          className="animate-pulse-live h-2 w-2 rounded-full bg-red-500"
          aria-hidden="true"
        />
      )}
      <span className="font-mono text-sm font-semibold text-[--text-primary] tabular-nums">
        {formatClock(minute, second)}
      </span>
      <span className="text-[10px] font-medium uppercase tracking-widest text-[--text-muted]">
        {period === 1 ? "1H" : "2H"}
      </span>
    </div>
  );
}
