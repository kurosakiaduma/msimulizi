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
  | { type: "tick"; now: number };

const INITIAL_STATE: ClockState = {
  anchor: { anchorWall: 0, anchorMatch: 0, speed: 1 },
  matchSeconds: 0,
  isRunning: false,
};

function clockReducer(state: ClockState, action: ClockAction): ClockState {
  switch (action.type) {
    case "setRunning":
      return {
        anchor: action.running
          ? { ...state.anchor, anchorWall: action.now }
          : state.anchor,
        matchSeconds: state.anchor.anchorMatch,
        isRunning: action.running,
      };
    case "updateAnchor":
      return {
        anchor: action.anchor,
        matchSeconds: state.isRunning
          ? state.matchSeconds
          : action.anchor.anchorMatch,
        isRunning: state.isRunning,
      };
    case "tick": {
      const elapsed = (action.now - state.anchor.anchorWall) / 1000;
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
    toClock,
  };
}
