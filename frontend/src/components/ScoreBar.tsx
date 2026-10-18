"use client";

interface Props {
  teamHome: string;
  teamAway: string;
  scoreHome: number;
  scoreAway: number;
  xgHome?: number;
  xgAway?: number;
  showXg?: boolean;
}

export function ScoreBar({
  teamHome,
  teamAway,
  scoreHome,
  scoreAway,
  xgHome,
  xgAway,
  showXg = false,
}: Props) {
  return (
    <div
      className="flex items-center justify-between gap-4 px-4 py-2 rounded-lg
                 bg-[--bg-surface] border border-[--border-subtle]"
      role="status"
      aria-label={`Score: ${teamHome} ${scoreHome} — ${scoreAway} ${teamAway}`}
    >
      {/* Home team */}
      <div className="flex flex-col items-end min-w-0 flex-1">
        <span className="truncate text-xs font-semibold uppercase tracking-wide text-[--text-secondary]">
          {teamHome}
        </span>
        {showXg && xgHome !== undefined && (
          <span className="text-[10px] text-[--text-muted] tabular-nums">
            xG {xgHome.toFixed(2)}
          </span>
        )}
      </div>

      {/* Score */}
      <div className="flex items-center gap-1 shrink-0">
        <span className="font-mono text-2xl font-bold tabular-nums text-[--text-primary] w-7 text-center">
          {scoreHome}
        </span>
        <span className="text-[--text-muted] font-light text-lg">—</span>
        <span className="font-mono text-2xl font-bold tabular-nums text-[--text-primary] w-7 text-center">
          {scoreAway}
        </span>
      </div>

      {/* Away team */}
      <div className="flex flex-col items-start min-w-0 flex-1">
        <span className="truncate text-xs font-semibold uppercase tracking-wide text-[--text-secondary]">
          {teamAway}
        </span>
        {showXg && xgAway !== undefined && (
          <span className="text-[10px] text-[--text-muted] tabular-nums">
            xG {xgAway.toFixed(2)}
          </span>
        )}
      </div>
    </div>
  );
}
