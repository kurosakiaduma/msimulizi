"use client";

import { useEffect, useRef, useState } from "react";

interface Props {
  /** Public MP3 URL for the current commentary clip, if it has arrived. */
  src: string | null;
  /** Viewer preference. When false the clip is paused and the player hidden. */
  enabled: boolean;
  variant?: "compact" | "full";
}

/**
 * Commentary player for the normal and audio-only viewer modes.
 *
 * Audio is synthesised after the caption, so the URL arrives later via an
 * `audio_update` WebSocket message. Browsers may reject programmatic playback
 * (for example after a long period without a user gesture), so the component
 * exposes a visible "Play commentary" fallback instead of failing silently.
 */
export function CommentaryAudio({ src, enabled, variant = "compact" }: Props) {
  const audioRef = useRef<HTMLAudioElement | null>(null);
  const loadedSrc = useRef<string | null>(null);
  const [blocked, setBlocked] = useState(false);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const audio = audioRef.current;
    if (!audio) return;

    if (!enabled || !src) {
      audio.pause();
      if (!src) loadedSrc.current = null;
      return;
    }

    if (loadedSrc.current !== src || !audio.getAttribute("src")) {
      loadedSrc.current = src;
      setBlocked(false);
      setFailed(false);
      audio.src = src;
      audio.load();
    }

    try {
      const playback = audio.play();
      if (playback && typeof playback.catch === "function") {
        void playback.catch((error: unknown) => {
          if (
            error instanceof DOMException &&
            (error.name === "NotAllowedError" || error.name === "AbortError")
          ) {
            setBlocked(error.name === "NotAllowedError");
          }
        });
      }
    } catch {
      // Older browsers can throw synchronously instead of returning a promise.
      queueMicrotask(() => setBlocked(true));
    }
  }, [src, enabled]);

  function handleManualPlay() {
    const audio = audioRef.current;
    if (!audio) return;
    try {
      const playback = audio.play();
      if (playback && typeof playback.then === "function") {
        void playback
          .then(() => setBlocked(false))
          .catch(() => setBlocked(true));
      }
    } catch {
      setBlocked(true);
    }
  }

  if (!enabled) return null;

  const isFull = variant === "full";

  return (
    <section
      aria-label="Audio commentary player"
      aria-live="polite"
      className={
        isFull
          ? "w-full max-w-md flex flex-col gap-3 rounded-xl border border-[--border-subtle] bg-[--bg-elevated] p-4"
          : "flex flex-col gap-2 rounded-lg border border-[--border-subtle] bg-[--bg-inset] p-3"
      }
    >
      <div className="flex items-center justify-between gap-3">
        <span className="text-[10px] uppercase tracking-widest font-semibold text-[--text-muted]">
          Audio commentary
        </span>
        <span
          className={`text-[9px] font-mono uppercase tracking-wider ${
            src ? "text-emerald-400" : "text-[--text-muted]"
          }`}
        >
          {src ? "Ready" : "Waiting for audio"}
        </span>
      </div>

      <audio
        ref={audioRef}
        controls
        preload="auto"
        playsInline
        data-testid="commentary-audio"
        aria-label="Commentary audio"
        className={src ? "h-9 w-full" : "hidden"}
        onPlay={() => {
          setBlocked(false);
          setFailed(false);
        }}
        onError={() => setFailed(true)}
      >
        <track kind="captions" />
      </audio>

      {!src && (
        <p className="text-[10px] leading-relaxed text-[--text-muted]">
          Audio is generated after each caption and starts automatically when
          the clip is ready.
        </p>
      )}

      {blocked && (
        <button
          type="button"
          onClick={handleManualPlay}
          className="self-start rounded-md bg-violet-600 px-3 py-1.5 text-[11px] font-medium
                     text-white transition-colors hover:bg-violet-500
                     focus-visible:ring-2 focus-visible:ring-violet-500
                     focus-visible:ring-offset-2 focus-visible:ring-offset-[--bg-inset]"
        >
          Play commentary
        </button>
      )}

      {failed && (
        <p role="alert" className="text-[10px] text-amber-300">
          Audio could not be played. Live captions are unaffected.
        </p>
      )}
    </section>
  );
}
