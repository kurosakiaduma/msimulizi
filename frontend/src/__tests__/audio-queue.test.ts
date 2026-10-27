import { describe, expect, it } from "vitest";

import {
  MAX_PENDING_AUDIO,
  createAudioQueueState,
  enqueueAudio,
  finishCurrentAudio,
} from "@/lib/audioQueue";

const track = (cardId: string, url = `https://audio.test/${cardId}.mp3`) => ({
  cardId,
  url,
});

describe("commentary audio queue", () => {
  it("plays the first clip immediately", () => {
    const state = enqueueAudio(createAudioQueueState(), track("c1"));

    expect(state.current).toEqual(track("c1"));
    expect(state.pending).toEqual([]);
  });

  it("does not replace the clip that is already playing", () => {
    const first = enqueueAudio(createAudioQueueState(), track("c1"));
    const second = enqueueAudio(first, track("c2"));

    expect(second.current).toEqual(track("c1"));
    expect(second.pending).toEqual([track("c2")]);
  });

  it("promotes the next clip only after the current one ends", () => {
    const queued = enqueueAudio(
      enqueueAudio(createAudioQueueState(), track("c1")),
      track("c2")
    );

    const finished = finishCurrentAudio(queued);

    expect(finished.current).toEqual(track("c2"));
    expect(finished.pending).toEqual([]);
  });

  it("ignores duplicate updates for the same card", () => {
    const state = enqueueAudio(createAudioQueueState(), track("c1"));

    expect(enqueueAudio(state, track("c1"))).toBe(state);
  });

  it("bounds the backlog by dropping the oldest waiting clip", () => {
    let state = enqueueAudio(createAudioQueueState(), track("current"));
    for (let index = 0; index < MAX_PENDING_AUDIO + 2; index += 1) {
      state = enqueueAudio(state, track(`pending-${index}`));
    }

    expect(state.current).toEqual(track("current"));
    expect(state.pending).toHaveLength(MAX_PENDING_AUDIO);
    expect(state.pending[0]).toEqual(track("pending-2"));
  });
});
