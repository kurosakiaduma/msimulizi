import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { Mock } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

import { CommentaryAudio } from "@/components/CommentaryAudio";

let playMock: Mock<() => Promise<void>>;
let pauseMock: Mock<() => void>;
let loadMock: Mock<() => void>;

beforeEach(() => {
  playMock = vi.fn<() => Promise<void>>().mockResolvedValue(undefined);
  pauseMock = vi.fn<() => void>();
  loadMock = vi.fn<() => void>();
  vi.spyOn(HTMLMediaElement.prototype, "play").mockImplementation(playMock);
  vi.spyOn(HTMLMediaElement.prototype, "pause").mockImplementation(pauseMock);
  vi.spyOn(HTMLMediaElement.prototype, "load").mockImplementation(loadMock);
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("CommentaryAudio", () => {
  it("starts playback when the late audio URL arrives", async () => {
    const { rerender } = render(
      <CommentaryAudio src={null} enabled={true} />
    );

    expect(playMock).not.toHaveBeenCalled();
    expect(screen.getByText(/waiting for audio/i)).toBeInTheDocument();

    rerender(
      <CommentaryAudio src="https://example.test/commentary.mp3" enabled={true} />
    );

    await waitFor(() => expect(playMock).toHaveBeenCalledTimes(1));
    expect(loadMock).toHaveBeenCalled();
    expect(screen.getByTestId("commentary-audio")).toHaveAttribute(
      "src",
      "https://example.test/commentary.mp3"
    );
  });

  it("offers a manual play button when autoplay is blocked", async () => {
    playMock.mockRejectedValueOnce(
      new DOMException("Autoplay blocked", "NotAllowedError")
    );

    render(
      <CommentaryAudio src="https://example.test/commentary.mp3" enabled={true} />
    );

    expect(
      await screen.findByRole("button", { name: /play commentary/i })
    ).toBeInTheDocument();
  });

  it("keeps the current clip playing when a later caption has no audio yet", async () => {
    const { rerender } = render(
      <CommentaryAudio
        src="https://example.test/first.mp3"
        trackId="card-1"
        enabled={true}
      />
    );

    await waitFor(() => expect(playMock).toHaveBeenCalledTimes(1));
    pauseMock.mockClear();

    rerender(
      <CommentaryAudio
        src="https://example.test/first.mp3"
        trackId="card-1"
        enabled={true}
      />
    );

    expect(pauseMock).not.toHaveBeenCalled();
    expect(playMock).toHaveBeenCalledTimes(1);
  });

  it("reloads a cached URL when the next card reuses it", async () => {
    const { rerender } = render(
      <CommentaryAudio
        src="https://example.test/shared.mp3"
        trackId="card-1"
        enabled={true}
      />
    );

    await waitFor(() => expect(loadMock).toHaveBeenCalledTimes(1));

    rerender(
      <CommentaryAudio
        src="https://example.test/shared.mp3"
        trackId="card-2"
        enabled={true}
      />
    );

    await waitFor(() => expect(loadMock).toHaveBeenCalledTimes(2));
    expect(playMock).toHaveBeenCalledTimes(2);
  });

  it("notifies the page when the current clip ends", async () => {
    const onEnded = vi.fn();
    render(
      <CommentaryAudio
        src="https://example.test/commentary.mp3"
        trackId="card-1"
        enabled={true}
        onEnded={onEnded}
      />
    );

    await waitFor(() => expect(playMock).toHaveBeenCalledTimes(1));
    fireEvent.ended(screen.getByTestId("commentary-audio"));

    expect(onEnded).toHaveBeenCalledTimes(1);
  });

  it("does not render or play when audio commentary is disabled", () => {
    render(
      <CommentaryAudio src="https://example.test/commentary.mp3" enabled={false} />
    );

    expect(screen.queryByTestId("commentary-audio")).not.toBeInTheDocument();
    expect(playMock).not.toHaveBeenCalled();
  });
});
