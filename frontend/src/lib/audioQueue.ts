/**
 * Client-side commentary audio queue.
 *
 * Captions are allowed to arrive faster than the spoken clips. The player must
 * finish the current clip before starting the next one instead of replacing the
 * audio source mid-sentence. This module keeps that ordering outside the
 * component so it can be tested without a real HTMLAudioElement.
 */

export interface AudioTrack {
  url: string;
  cardId: string;
}

export interface AudioQueueState {
  current: AudioTrack | null;
  pending: AudioTrack[];
}

/** Keep only a short backlog so a high replay speed cannot queue minutes of audio. */
export const MAX_PENDING_AUDIO = 3;

export function createAudioQueueState(): AudioQueueState {
  return { current: null, pending: [] };
}

/**
 * Add a newly available clip.
 *
 * - A clip already playing is never replaced; the new clip waits.
 * - Duplicate updates for the same card are ignored.
 * - The oldest pending clip is dropped when the backlog is full.
 */
export function enqueueAudio(
  state: AudioQueueState,
  track: AudioTrack
): AudioQueueState {
  if (!track.url) return state;

  if (state.current?.cardId === track.cardId) {
    return state;
  }

  const pendingIndex = state.pending.findIndex(
    (candidate) => candidate.cardId === track.cardId
  );
  if (pendingIndex >= 0) {
    if (state.pending[pendingIndex].url === track.url) return state;
    const pending = [...state.pending];
    pending[pendingIndex] = track;
    return { ...state, pending };
  }

  if (state.current === null) {
    return { current: track, pending: state.pending };
  }

  const pending = [...state.pending, track];
  if (pending.length > MAX_PENDING_AUDIO) {
    pending.splice(0, pending.length - MAX_PENDING_AUDIO);
  }
  return { ...state, pending };
}

/** Promote the next queued clip after the current one ends or fails. */
export function finishCurrentAudio(state: AudioQueueState): AudioQueueState {
  if (state.pending.length === 0) {
    return { current: null, pending: [] };
  }
  const [next, ...pending] = state.pending;
  return { current: next, pending };
}

export function clearAudioQueue(): AudioQueueState {
  return createAudioQueueState();
}
