import { act, renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useSessionClock } from "@/hooks/useSessionClock";

describe("useSessionClock start gate", () => {
  let nowMs = 0;
  let rafId = 0;
  const rafCallbacks = new Map<number, FrameRequestCallback>();

  beforeEach(() => {
    nowMs = 0;
    rafId = 0;
    rafCallbacks.clear();
    vi.spyOn(Date, "now").mockImplementation(() => nowMs);
    vi.stubGlobal("requestAnimationFrame", (cb: FrameRequestCallback) => {
      rafId += 1;
      rafCallbacks.set(rafId, cb);
      return rafId;
    });
    vi.stubGlobal("cancelAnimationFrame", (id: number) => {
      rafCallbacks.delete(id);
    });
  });

  afterEach(() => {
    vi.restoreAllMocks();
    vi.unstubAllGlobals();
  });

  it("does not advance match time until setRunning(true) is called", () => {
    const { result } = renderHook(() => useSessionClock());

    expect(result.current.matchSeconds).toBe(0);
    expect(result.current.isRunning).toBe(false);

    nowMs += 3000;
    expect(result.current.matchSeconds).toBe(0);

    act(() => {
      result.current.setRunning(true);
    });
    expect(result.current.isRunning).toBe(true);

    act(() => {
      nowMs += 2000;
      const callback = rafCallbacks.values().next().value as FrameRequestCallback | undefined;
      callback?.(nowMs);
    });
    expect(result.current.matchSeconds).toBeGreaterThan(1.5);
  });

  it("never rewinds when an older backend anchor arrives after a forward one", () => {
    const { result } = renderHook(() => useSessionClock());

    act(() => {
      result.current.setRunning(true);
      result.current.updateAnchor(0, 12 * 60 + 1, 1);
    });

    act(() => {
      nowMs += 30_000;
      const callback = rafCallbacks.values().next().value as FrameRequestCallback | undefined;
      callback?.(nowMs);
    });

    expect(result.current.matchSeconds).toBeGreaterThan(12 * 60 + 1);

    act(() => {
      result.current.updateAnchor(nowMs, 6 * 60, 1);
    });

    expect(result.current.matchSeconds).toBeGreaterThanOrEqual(12 * 60 + 1);
  });

  it("pauses and resumes without rewinding to the last anchor", () => {
    const { result } = renderHook(() => useSessionClock());

    act(() => {
      result.current.setRunning(true);
      result.current.updateAnchor(0, 30 * 60, 1);
      nowMs += 10_000;
      const callback = rafCallbacks.values().next().value as FrameRequestCallback | undefined;
      callback?.(nowMs);
    });

    const beforePause = result.current.matchSeconds;
    act(() => result.current.setRunning(false));
    expect(result.current.matchSeconds).toBeGreaterThanOrEqual(beforePause);

    act(() => result.current.setRunning(true));
    expect(result.current.matchSeconds).toBeGreaterThanOrEqual(beforePause);
  });

  it("resets to zero and stops when a new replay starts", () => {
    const { result } = renderHook(() => useSessionClock());

    act(() => {
      result.current.setRunning(true);
      result.current.updateAnchor(0, 40 * 60, 1);
    });
    expect(result.current.matchSeconds).toBe(40 * 60);

    act(() => {
      result.current.reset();
    });

    expect(result.current.matchSeconds).toBe(0);
    expect(result.current.isRunning).toBe(false);
  });
});
