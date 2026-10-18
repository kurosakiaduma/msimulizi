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
});
