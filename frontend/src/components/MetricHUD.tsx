"use client";

import type { MatchState } from "@/lib/types";

interface Props {
  state: MatchState;
}

function Bar({ label, value, max = 100, color = "bg-violet-500", unit = "%" }: {
  label: string;
  value: number;
  max?: number;
  color?: string;
  unit?: string;
}) {
  const pct = Math.min(100, (value / max) * 100);
  const display = unit === "%" ? `${Math.round(value * 100)}%` : value.toFixed(2);

  return (
    <div className="flex flex-col gap-0.5" role="meter" aria-label={`${label}: ${display}`}
         aria-valuenow={value} aria-valuemin={0} aria-valuemax={max}>
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-medium uppercase tracking-wider text-[--text-muted]">
          {label}
        </span>
        <span className="font-mono text-[11px] text-[--text-secondary] tabular-nums">
          {display}
        </span>
      </div>
      <div className="h-1 w-full rounded-full bg-white/5">
        <div
          className={`h-1 rounded-full transition-all duration-500 ${color}`}
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  );
}

function DualBar({ label, homeVal, awayVal, homeLabel, awayLabel }: {
  label: string;
  homeVal: number;
  awayVal: number;
  homeLabel: string;
  awayLabel: string;
}) {
  const total = homeVal + awayVal || 1;
  const homePct = (homeVal / total) * 100;
  const awayPct = (awayVal / total) * 100;

  return (
    <div className="flex flex-col gap-0.5" role="meter" aria-label={`${label}: ${homeLabel} ${Math.round(homePct)}% vs ${awayLabel} ${Math.round(awayPct)}%`}>
      <div className="flex items-center justify-between">
        <span className="text-[10px] font-medium uppercase tracking-wider text-[--text-muted]">
          {label}
        </span>
        <div className="flex gap-1 text-[10px] tabular-nums text-[--text-secondary]">
          <span>{Math.round(homePct)}%</span>
          <span className="text-[--text-muted]">/</span>
          <span>{Math.round(awayPct)}%</span>
        </div>
      </div>
      <div className="h-1 w-full rounded-full bg-white/5 flex overflow-hidden">
        <div
          className="h-1 bg-violet-500 transition-all duration-500"
          style={{ width: `${homePct}%` }}
        />
        <div
          className="h-1 bg-emerald-500 transition-all duration-500"
          style={{ width: `${awayPct}%` }}
        />
      </div>
    </div>
  );
}

export function MetricHUD({ state }: Props) {
  return (
    <section
      aria-label="Match metrics"
      className="flex flex-col gap-3 p-3 rounded-lg bg-[--bg-inset] border border-[--border-subtle]"
    >
      <h3 className="text-[10px] font-semibold uppercase tracking-widest text-[--text-muted]">
        Live Metrics
      </h3>

      <DualBar
        label="Possession"
        homeVal={state.possession_home}
        awayVal={1 - state.possession_home}
        homeLabel={state.team_home}
        awayLabel={state.team_away}
      />

      <DualBar
        label="Field Tilt"
        homeVal={state.field_tilt_home}
        awayVal={state.field_tilt_away}
        homeLabel={state.team_home}
        awayLabel={state.team_away}
      />

      <div className="flex gap-3">
        <div className="flex-1">
          <Bar
            label={`xG ${state.team_home.slice(0, 6)}`}
            value={state.xg_home}
            max={5}
            unit="float"
            color="bg-violet-500"
          />
        </div>
        <div className="flex-1">
          <Bar
            label={`xG ${state.team_away.slice(0, 6)}`}
            value={state.xg_away}
            max={5}
            unit="float"
            color="bg-emerald-500"
          />
        </div>
      </div>

      <Bar
        label="Tempo (ev/min)"
        value={state.tempo}
        max={30}
        unit="float"
        color="bg-blue-500"
      />

      <DualBar
        label="Momentum"
        homeVal={state.momentum_home}
        awayVal={state.momentum_away}
        homeLabel={state.team_home}
        awayLabel={state.team_away}
      />
    </section>
  );
}
