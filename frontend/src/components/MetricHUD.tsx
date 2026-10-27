"use client";

import type { EventDot, MatchState } from "@/lib/types";

interface Props {
  state: MatchState;
  /** Recent event dots, used for the analyst-mode team stat table. */
  events?: EventDot[];
}

interface TeamStatLine {
  shots: number;
  goals: number;
  passes: number;
  tackles: number;
  cards: number;
}

function emptyStatLine(): TeamStatLine {
  return { shots: 0, goals: 0, passes: 0, tackles: 0, cards: 0 };
}

function teamStats(events: EventDot[], homeTeam: string, awayTeam: string) {
  const home = emptyStatLine();
  const away = emptyStatLine();

  for (const event of events) {
    const line = event.team === homeTeam ? home : event.team === awayTeam ? away : null;
    if (!line) continue;

    switch (event.event_type) {
      case "shot":
        line.shots += 1;
        break;
      case "goal":
        line.goals += 1;
        line.shots += 1;
        break;
      case "pass":
        line.passes += 1;
        break;
      case "tackle":
      case "interception":
        line.tackles += 1;
        break;
      case "card":
        line.cards += 1;
        break;
      default:
        break;
    }
  }

  return { home, away };
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
    <div
      className="flex flex-col gap-0.5"
      role="meter"
      aria-label={`${label}: ${homeLabel} ${Math.round(homePct)}% vs ${awayLabel} ${Math.round(awayPct)}%`}
      aria-valuenow={Math.round(homePct)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
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

export function MetricHUD({ state, events = [] }: Props) {
  const stats = teamStats(events, state.team_home, state.team_away);

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

      <div className="pt-1 border-t border-[--border-subtle]">
        <h4 className="text-[10px] font-semibold uppercase tracking-widest text-[--text-muted] mb-2">
          Event Stats
        </h4>
        <table className="w-full text-[10px] tabular-nums" aria-label="Team event statistics">
          <thead>
            <tr className="text-[--text-muted]">
              <th scope="col" className="text-left font-medium pb-1">Team</th>
              <th scope="col" className="text-right font-medium pb-1">Shots</th>
              <th scope="col" className="text-right font-medium pb-1">Goals</th>
              <th scope="col" className="text-right font-medium pb-1">Passes</th>
              <th scope="col" className="text-right font-medium pb-1">Tackles</th>
            </tr>
          </thead>
          <tbody>
            <tr className="text-[--text-secondary]">
              <th scope="row" className="text-left font-medium py-0.5 truncate max-w-[10rem]">
                {state.team_home}
              </th>
              <td className="text-right">{stats.home.shots}</td>
              <td className="text-right">{stats.home.goals}</td>
              <td className="text-right">{stats.home.passes}</td>
              <td className="text-right">{stats.home.tackles}</td>
            </tr>
            <tr className="text-[--text-secondary]">
              <th scope="row" className="text-left font-medium py-0.5 truncate max-w-[10rem]">
                {state.team_away}
              </th>
              <td className="text-right">{stats.away.shots}</td>
              <td className="text-right">{stats.away.goals}</td>
              <td className="text-right">{stats.away.passes}</td>
              <td className="text-right">{stats.away.tackles}</td>
            </tr>
          </tbody>
        </table>
      </div>
    </section>
  );
}
