"use client";

import type { ViewerProfile, Language, Mode, ClubPerspective } from "@/lib/types";

interface Props {
  profile: ViewerProfile;
  homeTeam: string;
  awayTeam: string;
  homePlayers?: string[];
  awayPlayers?: string[];
  hasStarted?: boolean;
  onChange: (p: ViewerProfile) => void;
}

const METRIC_OPTIONS = [
  { value: "", label: "None" },
  { value: "xg", label: "xG" },
  { value: "possession", label: "Possession" },
  { value: "field_tilt", label: "Field Tilt" },
  { value: "pressure", label: "Pressure" },
  { value: "tempo", label: "Tempo" },
];

function RadioGroup<T extends string>({
  label,
  options,
  value,
  onChange,
  id,
}: {
  label: string;
  options: { value: T; label: string }[];
  value: T;
  onChange: (v: T) => void;
  id?: string;
}) {
  const groupId = id ?? label.toLowerCase().replace(/\s+/g, "-");
  return (
    <fieldset>
      <legend className="text-[9px] uppercase tracking-widest font-semibold text-[--text-muted] mb-1.5">
        {label}
      </legend>
      <div className="flex flex-wrap gap-1" role="group">
        {options.map((opt) => {
          const inputId = `${groupId}-${opt.value || "none"}`;
          const isActive = opt.value === value;
          return (
            <label
              key={opt.value}
              htmlFor={inputId}
              className={`cursor-pointer rounded-md px-3 py-1 text-[11px] font-medium transition-all
                          border select-none focus-within:ring-2 focus-within:ring-violet-500 focus-within:ring-offset-1
                          focus-within:ring-offset-[--bg-elevated]
                          ${isActive
                            ? "bg-violet-600 border-violet-500 text-white"
                            : "bg-[--bg-inset] border-[--border-subtle] text-[--text-secondary] hover:border-[--border-default]"
                          }`}
            >
              <input
                type="radio"
                id={inputId}
                name={groupId}
                value={opt.value}
                checked={isActive}
                onChange={() => onChange(opt.value)}
                className="sr-only"
              />
              {opt.label}
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}

export function PersonalisationPanel({ profile, homeTeam, awayTeam, homePlayers = [], awayPlayers = [], hasStarted = false, onChange }: Props) {
  // Build suggested players based on club focus
  const suggestedPlayers =
    profile.club_perspective === "home" ? homePlayers :
    profile.club_perspective === "away" ? awayPlayers :
    [...homePlayers, ...awayPlayers];
  return (
    <section
      aria-label="Viewer profile settings"
      className="flex flex-col gap-4 p-4 rounded-xl bg-[--bg-elevated] border border-[--border-subtle]"
    >
      <h2 className="text-[10px] font-bold uppercase tracking-widest text-[--text-muted]">
        Profile Tuner
      </h2>

      <RadioGroup<Language>
        label="Language"
        id="profile-language"
        value={profile.language}
        options={[
          { value: "sw", label: "Swahili" },
          { value: "en", label: "English" },
          { value: "fr", label: "Français" },
        ]}
        onChange={(language) => onChange({ ...profile, language })}
      />

      {hasStarted && (
        <div className="rounded-md bg-amber-500/10 border border-amber-500/30 px-3 py-2">
          <p className="text-[10px] text-amber-200 leading-tight">
            <span className="font-semibold">Note:</span> Language changes during a match
            only affect new cards. Existing cards will show the original language.
            Restart the match for full language change.
          </p>
        </div>
      )}

      <RadioGroup<Mode>
        label="Mode"
        id="profile-mode"
        value={profile.mode}
        options={[
          { value: "casual", label: "Casual Fan" },
          { value: "analyst", label: "Analyst" },
        ]}
        onChange={(mode) => onChange({ ...profile, mode })}
      />

      <RadioGroup<ClubPerspective>
        label="Club Focus"
        id="profile-club"
        value={profile.club_perspective}
        options={[
          { value: "home",    label: homeTeam || "Home" },
          { value: "away",    label: awayTeam || "Away" },
          { value: "neutral", label: "Neutral" },
        ]}
        onChange={(club_perspective) => onChange({ ...profile, club_perspective })}
      />

      {/* Favourite player text input */}
      <div className="flex flex-col gap-1">
        <label
          htmlFor="favourite-player"
          className="text-[9px] uppercase tracking-widest font-semibold text-[--text-muted]"
        >
          Favourite Player
        </label>
        <input
          id="favourite-player"
          type="text"
          list="player-suggestions"
          value={profile.favourite_player ?? ""}
          onChange={(e) =>
            onChange({ ...profile, favourite_player: e.target.value.trim() || null })
          }
          placeholder="Player name…"
          className="rounded-md bg-[--bg-inset] border border-[--border-subtle] text-[11px]
                     text-[--text-primary] placeholder-[--text-muted] px-3 py-1.5
                     focus:outline-none focus:border-violet-500/60 focus:ring-2 focus:ring-violet-500/30
                     transition-colors"
          aria-label="Favourite player name for spotlight cards"
          autoComplete="off"
        />
        {suggestedPlayers.length > 0 && (
          <datalist id="player-suggestions">
            {suggestedPlayers.map((p) => (
              <option key={p} value={p} />
            ))}
          </datalist>
        )}
      </div>

      {/* Metric focus — radio group to avoid native select contrast issues */}
      <RadioGroup<string>
        label="Metric Focus"
        id="profile-metric"
        value={profile.metric_focus ?? ""}
        options={METRIC_OPTIONS}
        onChange={(metric_focus) =>
          onChange({ ...profile, metric_focus: metric_focus || null })
        }
      />

      {/* Audio controls */}
      <div className="flex flex-col gap-2 pt-1 border-t border-[--border-subtle]">
        {/* Audio commentary toggle */}
        <div className="flex items-center justify-between">
          <span
            id="audio-commentary-label"
            className="text-[10px] uppercase tracking-widest font-semibold text-[--text-muted]"
          >
            Audio Commentary
          </span>
          <button
            role="switch"
            aria-checked={profile.audio_enabled}
            aria-labelledby="audio-commentary-label"
            onClick={() => onChange({ ...profile, audio_enabled: !profile.audio_enabled })}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors
                        focus-visible:ring-2 focus-visible:ring-violet-500 focus-visible:ring-offset-1
                        focus-visible:ring-offset-[--bg-elevated]
                        ${profile.audio_enabled ? "bg-violet-600" : "bg-white/10"}`}
            aria-label={`Audio commentary ${profile.audio_enabled ? "on" : "off"}`}
          >
            <span
              className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform
                          ${profile.audio_enabled ? "translate-x-4" : "translate-x-0.5"}`}
            />
          </button>
        </div>

        {/* Audio-only mode */}
        <div className="flex items-center justify-between">
          <span
            id="audio-only-label"
            className="text-[10px] uppercase tracking-widest font-semibold text-[--text-muted]"
          >
            Audio-Only Mode
          </span>
          <button
            role="switch"
            aria-checked={profile.audio_only}
            aria-labelledby="audio-only-label"
            onClick={() => onChange({ ...profile, audio_only: !profile.audio_only })}
            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors
                        focus-visible:ring-2 focus-visible:ring-violet-500 focus-visible:ring-offset-1
                        focus-visible:ring-offset-[--bg-elevated]
                        ${profile.audio_only ? "bg-violet-600" : "bg-white/10"}`}
            aria-label={`Audio-only mode ${profile.audio_only ? "on" : "off"}`}
          >
            <span
              className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform
                          ${profile.audio_only ? "translate-x-4" : "translate-x-0.5"}`}
            />
          </button>
        </div>
      </div>
    </section>
  );
}
