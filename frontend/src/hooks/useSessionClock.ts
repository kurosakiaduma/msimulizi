"use client";

import { useCallback, useEffect, useReducer, useRef } from "react";

interface ClockAnchor {
  anchorWall: number;
  anchorMatch: number;
  speed: number;
}

interface ClockState {
  anchor: ClockAnchor;
  matchSeconds: number;
  isRunning: boolean;
}

type ClockAction =
  | { type: "setRunning"; running: boolean; now: number }
  | { type: "updateAnchor"; anchor: ClockAnchor }
  | { type: "reset"; now: number }
  | { type: "tick"; now: number };

const INITIAL_STATE: ClockState = {
  anchor: { anchorWall: 0, anchorMatch: 0, speed: 1 },
  matchSeconds: 0,
  isRunning: false,
};

function clockReducer(state: ClockState, action: ClockAction): ClockState {
  switch (action.type) {
    case "setRunning": {
      // Resume from the currently visible time, not from the last anchor.
      // The reducer ticks every frame, so anchor.anchorMatch is usually older
      // than matchSeconds; using it here would make the clock jump backwards
      // on a pause/resume or a reconnect.
      const matchSeconds = state.matchSeconds;
      return {
        anchor: {
          ...state.anchor,
          anchorWall: action.now,
          anchorMatch: matchSeconds,
        },
        matchSeconds,
        isRunning: action.running,
      };
    }
    case "updateAnchor": {
      // Backend and card timestamps can arrive a few seconds out of order
      // after a slow LLM/TTS turn. Never let an older anchor pull the visible
      // clock backwards; move to the newest forward anchor instead.
      const anchorMatch = state.isRunning
        ? Math.max(action.anchor.anchorMatch, state.matchSeconds)
        : action.anchor.anchorMatch;
      return {
        anchor: { ...action.anchor, anchorMatch },
        matchSeconds: state.isRunning ? anchorMatch : action.anchor.anchorMatch,
        isRunning: state.isRunning,
      };
    }
    case "reset":
      return {
        anchor: { anchorWall: action.now, anchorMatch: 0, speed: 1 },
        matchSeconds: 0,
        isRunning: false,
      };
    case "tick": {
      const elapsed = Math.max(0, (action.now - state.anchor.anchorWall) / 1000);
      return {
        ...state,
        matchSeconds: state.anchor.anchorMatch + elapsed * state.anchor.speed,
      };
    }
  }
}

export function useSessionClock() {
  const [state, dispatch] = useReducer(clockReducer, INITIAL_STATE);
  const rafRef = useRef<number | null>(null);

  const updateAnchor = useCallback((
    anchorWall: number,
    anchorMatch: number,
    speed: number
  ) => {
    dispatch({
      type: "updateAnchor",
      anchor: { anchorWall, anchorMatch, speed },
    });
  }, []);

  const setRunning = useCallback((running: boolean) => {
    dispatch({ type: "setRunning", running, now: Date.now() });
  }, []);

  const reset = useCallback(() => {
    dispatch({ type: "reset", now: Date.now() });
  }, []);

  useEffect(() => {
    if (!state.isRunning) {
      if (rafRef.current !== null) {
        cancelAnimationFrame(rafRef.current);
        rafRef.current = null;
      }
      return;
    }

    const tick = () => {
      dispatch({ type: "tick", now: Date.now() });
      rafRef.current = requestAnimationFrame(tick);
    };
    rafRef.current = requestAnimationFrame(tick);
    return () => {
      if (rafRef.current !== null) cancelAnimationFrame(rafRef.current);
    };
  }, [state.isRunning]);

  /** Convert match_seconds to display clock (minute, second) */
  const toClock = useCallback((secs: number) => {
    const s = Math.max(0, Math.floor(secs));
    return { minute: Math.floor(s / 60), second: s % 60 };
  }, []);

  return {
    matchSeconds: state.matchSeconds,
    anchorWall: state.anchor.anchorWall,
    anchorMatch: state.anchor.anchorMatch,
    speed: state.anchor.speed,
    isRunning: state.isRunning,
    updateAnchor,
    setRunning,
    reset,
    toClock,
  };
}
