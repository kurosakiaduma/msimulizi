"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import type {
  ViewerProfile,
  MatchState,
  EventDot,
  OverlayCard,
  WsMessage,
} from "@/lib/types";
import { useSessionClock } from "@/hooks/useSessionClock";
import { useMatchSocket } from "@/hooks/useMatchSocket";
import {
  applyAudioUrl,
  createSchedulerState,
  enqueueCard,
  tick,
} from "@/lib/scheduler";
import type { SchedulerState } from "@/lib/scheduler";
import { loadRuntimeConfig } from "@/lib/runtimeConfig";

import { MatchClock } from "@/components/MatchClock";
import { ScoreBar } from "@/components/ScoreBar";
import { PitchVisual } from "@/components/PitchVisual";
import { MetricHUD } from "@/components/MetricHUD";
import { CardFeed } from "@/components/CardFeed";
import { CommentaryAudio } from "@/components/CommentaryAudio";
import { PersonalisationPanel } from "@/components/PersonalisationPanel";
import { ReplayPanel, STORYLINES } from "@/components/ReplayPanel";

// ── Storyline player rosters (for datalist suggestions) ──────────────────

const STORYLINE_PLAYERS: Record<string, { home: string[]; away: string[] }> = {
  comeback_from_two_down: {
    home: ["Amani Otieno", "Khalid Njoroge", "Juma Kamau", "Davis Wekesa", "Eliud Mwangangi"],
    away: ["Nuru Mchana", "Salim Kivuva", "Juma Mwakazi", "Asha Njeri", "Mbaraka Chacha"],
  },
  red_card_shift: {
    home: ["Brian Ouma", "Eric Muita", "Samson Kariuki", "Teddy Mwangi", "Peter Kioko"],
    away: ["Harun Kiptanui", "David Karanja", "Joseph Miti", "Franklin Ndegwa", "Lukman Ochieng"],
  },
  late_equaliser: {
    home: ["Isaac Adera", "Moses Ndege", "Kevin Mburu", "Daniel Mwakio", "Tariq Zuberi"],
    away: ["Levi Makori", "Abdullah Sami", "Zuberi Ali", "Pius Mnyamala", "Noel Kamau"],
  },
  dominant_side_loses: {
    home: ["Willy Kibet", "Ibrahim Juma", "Moses Omondi", "Abdi Yusuf", "Paul Kasa"],
    away: ["Yusuf Msuya", "Alfred Mpepo", "Benson Tiba", "Daniel Sanga", "Emmanuel Kaso"],
  },
};

// ── Default / stub state ──────────────────────────────────────────────────

const DEFAULT_MATCH_STATE: MatchState = {
  match_id: "",
  minute: 0,
  second: 0,
  score_home: 0,
  score_away: 0,
  possession_home: 0.5,
  field_tilt_home: 0.5,
  field_tilt_away: 0.5,
  xg_home: 0,
  xg_away: 0,
  momentum_home: 50,
  momentum_away: 50,
  pressure_rate_home: 0,
  pressure_rate_away: 0,
  tempo: 12,
  team_home: "Nyota FC",
  team_away: "Jua United",
};

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

// ─────────────────────────────────────────────────────────────────────────

export default function Home() {
  const [profile, setProfile] = useState<ViewerProfile>(DEFAULT_PROFILE);
  const [matchState, setMatchState] = useState<MatchState>(DEFAULT_MATCH_STATE);
  const [events, setEvents] = useState<EventDot[]>([]);
  const [latestEvent, setLatestEvent] = useState<EventDot | null>(null);
  const [cardHistory, setCardHistory] = useState<OverlayCard[]>([]);
  const [audioTrack, setAudioTrack] = useState<{ url: string; cardId: string } | null>(null);
  const [scheduler, setScheduler] = useState<SchedulerState>(createSchedulerState());
  const [selectedStoryline, setSelectedStoryline] = useState(STORYLINES[0].id);
  const [replaySpeed, setReplaySpeed] = useState(1.0);
  const [isConnected, setIsConnected] = useState(false);
  const [hasStarted, setHasStarted] = useState(false);
  const [isFinished, setIsFinished] = useState(false);
  const [wsUrl, setWsUrl] = useState<string | null>(null);

  const clock = useSessionClock();
  const schedulerRef = useRef(scheduler);

  useEffect(() => {
    clock.setRunning(hasStarted);
  }, [clock.setRunning, hasStarted]);

  // Keep ref in sync with scheduler state
  useEffect(() => {
    schedulerRef.current = scheduler;
  }, [scheduler]);

  // ── Scheduler tick ───────────────────────────────────────────────────
  useEffect(() => {
    const id = setInterval(() => {
      setScheduler((s) => tick(s, Date.now()));
    }, 100);
    return () => clearInterval(id);
  }, []);

  // ── WebSocket message handler ────────────────────────────────────────
  const handleMessage = useCallback(
    (msg: WsMessage) => {
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const raw = msg as any;

      // Event-dot packets arrive via clock_update channel with an event_id field
      if (msg.type === "clock_update" && raw.clock?.event_id) {
        const c = raw.clock;
        const dot: EventDot = {
          event_id: c.event_id,
          x: c.x ?? 50,
          y: c.y ?? 50,
          event_type: c.event_type ?? "pass",
          team: c.team ?? "",
          team_side: c.team_side ?? "",
          player: c.player ?? "",
          minute: c.minute ?? 0,
          outcome: c.outcome ?? null,
        };
        setLatestEvent(dot);
        setEvents((prev) => [...prev.slice(-200), dot]);
        return;
      }

      // full_time arrives wrapped in the clock_update channel
      if (msg.type === "clock_update" && raw.clock?.type === "full_time") {
        setIsFinished(true);
        clock.updateAnchor(Date.now(), 90 * 60, 0);
        return;
      }

      switch (msg.type) {
        case "state_update":
          setMatchState(msg.payload);
          // Re-anchor the match clock to the authoritative backend time so the
          // topbar timer stays in sync with cards and events instead of
          // counting up independently from session start.
          clock.updateAnchor(
            Date.now(),
            msg.payload.minute * 60 + msg.payload.second,
            clock.speed
          );
          break;

        case "event": {
          const dot: EventDot = {
            event_id: raw.event_id ?? raw.payload?.event_id ?? "",
            x: raw.x ?? raw.payload?.x ?? 50,
            y: raw.y ?? raw.payload?.y ?? 50,
            event_type: raw.event_type ?? raw.payload?.event_type ?? "pass",
            team: raw.team ?? raw.payload?.team ?? "",
            team_side: raw.team_side ?? raw.payload?.team_side ?? "",
            player: raw.player ?? raw.payload?.player ?? "",
            minute: raw.minute ?? raw.payload?.minute ?? 0,
            outcome: raw.outcome ?? raw.payload?.outcome ?? null,
          };
          setLatestEvent(dot);
          setEvents((prev) => [...prev.slice(-200), dot]);
          // Re-anchor the clock to the event's authoritative match minute so the
          // timer stays synced even between less frequent state/card updates.
          clock.updateAnchor(Date.now(), dot.minute * 60, clock.speed);
          break;
        }

        case "full_time":
          setIsFinished(true);
          clock.updateAnchor(Date.now(), 90 * 60, 0);
          break;

        case "score_update":
          setMatchState((s) => ({
            ...s,
            score_home: msg.home,
            score_away: msg.away,
            minute: msg.minute,
          }));
          clock.updateAnchor(Date.now(), msg.minute * 60, clock.speed);
          break;

        case "clock_update": {
          const c = msg.clock;
          const matchSecs =
            c.match_seconds ?? ((c.minute ?? 0) * 60 + (c.second ?? 0));
          const spd = c.speed ?? clock.speed;
          // Use the authoritative event time at the moment the packet is
          // received. The backend's wall anchor is useful for other clients,
          // but using it here made the clock drift ahead during slow LLM/TTS
          // turns and then snap backwards when a card re-anchored.
          clock.updateAnchor(Date.now(), matchSecs, spd);
          setMatchState((s) => ({
            ...s,
            score_home: c.score_home ?? s.score_home,
            score_away: c.score_away ?? s.score_away,
            minute: c.minute ?? s.minute,
            second: c.second ?? s.second,
            momentum_home: c.momentum_home ?? s.momentum_home,
            momentum_away: c.momentum_away ?? s.momentum_away,
            possession_home: c.possession_home ?? s.possession_home,
            xg_home: c.xg_home ?? s.xg_home,
            xg_away: c.xg_away ?? s.xg_away,
            field_tilt_home: c.field_tilt_home ?? s.field_tilt_home,
            field_tilt_away: c.field_tilt_away ?? s.field_tilt_away,
            tempo: c.tempo ?? s.tempo,
          }));
          break;
        }

        case "card": {
          const card = msg.card;
          if (!card) break;
          // Re-anchor the clock to the card's authoritative match time so the
          // topbar timer stays synced with the cards/events the backend
          // broadcasts instead of drifting from session start.
          const cardMatchSecs: number =
            (card.match_seconds as number | undefined) ??
            card.match_clock.minute * 60 + card.match_clock.second;
          clock.updateAnchor(Date.now(), cardMatchSecs, clock.speed);
          setScheduler((s) =>
            enqueueCard(
              s,
              card,
              clock.anchorWall,
              clock.anchorMatch,
              clock.speed,
              Date.now()
            )
          );
          setCardHistory((h) => [...h, card]);
          // Bundle cards can carry a pre-generated URL. For freshly narrated
          // cards the URL arrives later via audio_update.
          setAudioTrack(
            card.audio_url
              ? { url: card.audio_url, cardId: card.card_id }
              : null
          );
          break;
        }

        case "audio_update":
          setCardHistory((h) =>
            h.map((c) =>
              c.card_id === msg.card_id ? { ...c, audio_url: msg.audio_url } : c
            )
          );
          // Audio is synthesized after the caption. Patch the scheduler copy
          // too so the card view and audio-only mode stay in sync.
          setScheduler((s) =>
            applyAudioUrl(s, msg.card_id, msg.audio_url ?? null)
          );
          setAudioTrack((track) => {
            if (msg.audio_url) return { url: msg.audio_url, cardId: msg.card_id };
            return track?.cardId === msg.card_id ? null : track;
          });
          break;

        default:
          break;
      }
    },
    [clock]
  );

  const { send } = useMatchSocket({
    url: wsUrl,
    onMessage: handleMessage,
    onOpen: () => setIsConnected(true),
    onClose: () => setIsConnected(false),
  });

  // ── Session management ───────────────────────────────────────────────
  async function startSession(storylineId: string) {
    // Reset all state before starting
    setIsFinished(false);
    setHasStarted(false);
    setCardHistory([]);
    setAudioTrack(null);
    setEvents([]);
    setLatestEvent(null);
    setScheduler(createSchedulerState());
    setMatchState({ ...DEFAULT_MATCH_STATE });
    clock.reset();
    // Seed the clock at the chosen replay speed. The first authoritative
    // backend clock update re-anchors it without ever moving backwards.
    clock.updateAnchor(Date.now(), 0, replaySpeed);

    const config = await loadRuntimeConfig();

    try {
      const resp = await fetch(`${config.backendUrl}/v1/sessions`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          storyline: storylineId,
          seed: 42,
          speed: replaySpeed,
          language: profile.language,
          mode: profile.mode,
        }),
      });
      if (!resp.ok) throw new Error(`Session create failed: ${resp.status}`);
      const data = await resp.json();
      const sid: string = data.session_id;
      const mid: string = data.match_id;
      setWsUrl(`${config.wsUrl}?session_id=${sid}&match_id=${mid}`);
    } catch {
      const sid = `demo-${Date.now()}`;
      setWsUrl(`${config.wsUrl}?session_id=${sid}&storyline=${storylineId}`);
    }
    setHasStarted(true);
  }

  // Start with bundle replay on mount
  // DO NOT auto-start — user must explicitly click Start in the ReplayPanel.

  function handleSelectStoryline(id: string) {
    setSelectedStoryline(id);
  }

  function handleRestart() {
    void startSession(selectedStoryline);
  }

  function handleProfileChange(p: ViewerProfile) {
    setProfile(p);
    send({
      type: "profile_update",
      language: p.language,
      mode: p.mode,
      club_perspective: p.club_perspective,
      favourite_club: p.favourite_club,
      favourite_player: p.favourite_player,
      metric_focus: p.metric_focus,
      audio_only: p.audio_only,
    });
  }

  function handleThumbUp(cardId: string) {
    send({ type: "correction", card_id: cardId, rating: "up" });
  }
  function handleThumbDown(cardId: string) {
    send({ type: "correction", card_id: cardId, rating: "down" });
  }
  function handleSubmitEdit(cardId: string, text: string) {
    send({ type: "correction", card_id: cardId, rating: "edit", text });
  }

  // ── Derived clock values ─────────────────────────────────────────────
  // matchSeconds is a float advanced every animation frame. Rendering off it
  // directly re-renders the page at ~60fps, which makes the topbar clock and
  // cards jitter. Only commit a new clock to the UI when the displayed second
  // actually changes so the rendered clock stays stable between ticks.
  const [renderClock, setRenderClock] = useState<{ minute: number; second: number }>(
    clock.toClock(clock.matchSeconds)
  );
  const prevRenderClock = useRef(renderClock);

  useEffect(() => {
    const next = clock.toClock(clock.matchSeconds);
    if (
      next.minute !== prevRenderClock.current.minute ||
      next.second !== prevRenderClock.current.second
    ) {
      prevRenderClock.current = next;
      setRenderClock(next);
    }
  }, [clock.matchSeconds]);

  const isLive = isConnected;
  // Approximate period from match seconds
  const period = clock.matchSeconds < 2700 ? 1 : 2;

  const showAnalyst = profile.mode === "analyst";

  // ── Audio-only mode: show only clock + audio player (Req 9.5, 12.9) ─
  if (profile.audio_only) {
    return (
      <div className="min-h-screen bg-[--bg-base] flex flex-col items-center justify-center gap-6 p-8">
        <header aria-label="Match header (audio-only mode)">
          <MatchClock
            minute={renderClock.minute}
            second={renderClock.second}
            period={period as 1 | 2}
            isLive={isLive}
          />
        </header>
        <ScoreBar
          teamHome={matchState.team_home}
          teamAway={matchState.team_away}
          scoreHome={matchState.score_home}
          scoreAway={matchState.score_away}
        />
        {/* Audio-only mode is itself an explicit request for commentary. */}
        <CommentaryAudio
          src={audioTrack?.url ?? null}
          enabled
          variant="full"
        />
        <button
          onClick={() => handleProfileChange({ ...profile, audio_only: false })}
          className="text-xs text-[--text-muted] hover:text-[--text-primary] transition-colors
                     focus-visible:ring-2 focus-visible:ring-violet-500 px-3 py-1.5 rounded-md
                     border border-[--border-subtle]"
          aria-label="Exit audio-only mode"
        >
          Exit audio-only mode
        </button>
      </div>
    );
  }

  // ── Render ───────────────────────────────────────────────────────────
  return (
    <div className="min-h-screen bg-[--bg-base] flex flex-col">
      {/* ── Topbar ──────────────────────────────────────────────────── */}
      <header
        className="sticky top-0 z-30 flex items-center justify-between
                   px-4 py-2 bg-[--bg-surface]/90 backdrop-blur-sm
                   border-b border-[--border-subtle]"
        aria-label="Match header"
      >
        <div className="flex items-center gap-3">
          <span className="text-sm font-bold tracking-tight text-[--text-primary]">
            Msimulizi
          </span>
          <span className="hidden sm:block text-[10px] text-[--text-muted] uppercase tracking-wider">
            AI Match Intelligence
          </span>
          <nav aria-label="Site navigation" className="flex items-center gap-2 ml-2">
            <a
              href="/about"
              className="text-[10px] text-[--text-muted] hover:text-[--text-primary] transition-colors
                         focus-visible:ring-2 focus-visible:ring-violet-500 px-2 py-1 rounded"
            >
              About
            </a>
            <a
              href="/review"
              className="text-[10px] text-[--text-muted] hover:text-[--text-primary] transition-colors
                         focus-visible:ring-2 focus-visible:ring-violet-500 px-2 py-1 rounded"
            >
              Review
            </a>
          </nav>
        </div>

        <div className="flex items-center gap-4">
          <MatchClock
            minute={renderClock.minute}
            second={renderClock.second}
            period={period as 1 | 2}
            isLive={isLive}
          />
          <ScoreBar
            teamHome={matchState.team_home}
            teamAway={matchState.team_away}
            scoreHome={matchState.score_home}
            scoreAway={matchState.score_away}
          />
        </div>
      </header>

      {/* ── Main grid ───────────────────────────────────────────────── */}
      <main className="flex-1 flex flex-col lg:flex-row gap-0 overflow-hidden">

        {/* ── LEFT COLUMN: pitch + score + cards ────────────────────── */}
        <div
          className="lg:w-[62%] xl:w-[65%] flex flex-col gap-3 p-4 border-r border-[--border-subtle]
                     overflow-y-auto"
          aria-label="Match visualization and commentary"
        >
          {/* Pitch */}
          <PitchVisual
            events={events}
            latestEvent={latestEvent}
            homeTeam={matchState.team_home}
            awayTeam={matchState.team_away}
            showHeatmap={showAnalyst}
            className="flex-shrink-0 h-48 sm:h-64"
          />

          {/* ScoreBar */}
          <ScoreBar
            teamHome={matchState.team_home}
            teamAway={matchState.team_away}
            scoreHome={matchState.score_home}
            scoreAway={matchState.score_away}
            xgHome={matchState.xg_home}
            xgAway={matchState.xg_away}
            showXg={showAnalyst}
          />

          {/* Momentum / metric HUD */}
          {showAnalyst ? (
            <MetricHUD state={matchState} events={events} />
          ) : (
            <div
              className="flex items-center gap-3 p-3 rounded-lg bg-[--bg-inset] border border-[--border-subtle]"
              role="region"
              aria-label="Match momentum indicator"
            >
              <span className="text-[10px] uppercase tracking-widest text-[--text-muted] shrink-0">
                Momentum
              </span>
              <div className="flex-1 h-1.5 rounded-full bg-white/5 overflow-hidden flex">
                <div
                  className="h-1.5 bg-violet-500 transition-all duration-500"
                  style={{ width: `${matchState.momentum_home}%` }}
                />
                <div
                  className="h-1.5 bg-emerald-500 transition-all duration-500"
                  style={{ width: `${matchState.momentum_away}%` }}
                />
              </div>
              <span className="text-[10px] text-[--text-secondary] font-mono tabular-nums shrink-0">
                {Math.round(matchState.momentum_home)}–{Math.round(matchState.momentum_away)}
              </span>
            </div>
          )}

          {/* Commentary audio — captions remain the primary surface. */}
          <CommentaryAudio
            src={audioTrack?.url ?? null}
            enabled={profile.audio_enabled}
          />

          {/* Card feed — lives under the pitch */}
          <div className="flex-1 min-h-0">
            <CardFeed
              current={scheduler.current}
              history={cardHistory}
              language={profile.language}
              hasStarted={hasStarted}
              onThumbUp={handleThumbUp}
              onThumbDown={handleThumbDown}
              onSubmitEdit={handleSubmitEdit}
            />
          </div>
        </div>

        {/* ── RIGHT COLUMN: profile + replay controls ───────────────── */}
        <div
          className="flex-1 flex flex-col gap-3 p-4 overflow-y-auto"
          aria-label="Controls"
        >
          <PersonalisationPanel
            profile={profile}
            homeTeam={matchState.team_home}
            awayTeam={matchState.team_away}
            homePlayers={STORYLINE_PLAYERS[selectedStoryline]?.home ?? []}
            awayPlayers={STORYLINE_PLAYERS[selectedStoryline]?.away ?? []}
            hasStarted={hasStarted}
            onChange={handleProfileChange}
          />
          <ReplayPanel
            selectedStoryline={selectedStoryline}
            isConnected={isConnected}
            hasStarted={hasStarted}
            isFinished={isFinished}
            speed={replaySpeed}
            onSelectStoryline={handleSelectStoryline}
            onSelectSpeed={setReplaySpeed}
            onStart={handleRestart}
          />
        </div>
      </main>
    </div>
  );
}
