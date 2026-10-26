import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import type { Mock } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";

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

  it("does not render or play when audio commentary is disabled", () => {
    render(
      <CommentaryAudio src="https://example.test/commentary.mp3" enabled={false} />
    );

    expect(screen.queryByTestId("commentary-audio")).not.toBeInTheDocument();
    expect(playMock).not.toHaveBeenCalled();
  });
});
