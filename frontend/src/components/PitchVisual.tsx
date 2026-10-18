"use client";

import { useEffect, useRef } from "react";
import type { EventDot } from "@/lib/types";

interface Props {
  events: EventDot[];
  /** Most recent event for ball position */
  latestEvent?: EventDot | null;
  homeTeam: string;
  awayTeam: string;
  showHeatmap?: boolean;
  className?: string;
}

const EVENT_COLOR: Record<string, string> = {
  shot:         "#F59E0B",
  goal:         "#F59E0B",
  pass:         "#3B82F6",
  tackle:       "#22C55E",
  interception: "#22C55E",
  foul:         "#EF4444",
  card:         "#EF4444",
  default:      "#8A92A3",
};

function eventColor(type: string): string {
  return EVENT_COLOR[type] ?? EVENT_COLOR.default;
}

export function PitchVisual({
  events,
  latestEvent,
  homeTeam,
  awayTeam,
  showHeatmap = false,
  className = "",
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    const W = canvas.width;
    const H = canvas.height;

    // ── Clear ────────────────────────────────────────────────────────────
    ctx.clearRect(0, 0, W, H);

    // ── Pitch background ─────────────────────────────────────────────────
    const pitchGrad = ctx.createLinearGradient(0, 0, 0, H);
    pitchGrad.addColorStop(0,   "#1A3A1F");
    pitchGrad.addColorStop(0.5, "#163318");
    pitchGrad.addColorStop(1,   "#1A3A1F");
    ctx.fillStyle = pitchGrad;
    ctx.beginPath();
    ctx.roundRect(0, 0, W, H, 8);
    ctx.fill();

    // Stripe pattern
    ctx.globalAlpha = 0.04;
    ctx.fillStyle = "#ffffff";
    const stripeW = W / 10;
    for (let i = 0; i < 10; i += 2) {
      ctx.fillRect(i * stripeW, 0, stripeW, H);
    }
    ctx.globalAlpha = 1;

    const LINE = "rgba(255,255,255,0.22)";
    ctx.strokeStyle = LINE;
    ctx.lineWidth = 1;

    // ── Pitch outline ─────────────────────────────────────────────────────
    const pad = 8;
    ctx.strokeRect(pad, pad, W - pad * 2, H - pad * 2);

    // Half-way line
    ctx.beginPath();
    ctx.moveTo(W / 2, pad);
    ctx.lineTo(W / 2, H - pad);
    ctx.stroke();

    // Centre circle
    ctx.beginPath();
    ctx.arc(W / 2, H / 2, H * 0.14, 0, Math.PI * 2);
    ctx.stroke();

    // Centre spot
    ctx.fillStyle = LINE;
    ctx.beginPath();
    ctx.arc(W / 2, H / 2, 2, 0, Math.PI * 2);
    ctx.fill();

    // Penalty areas
    const paW = W * 0.16;
    const paH = H * 0.44;
    const paY = (H - paH) / 2;
    ctx.strokeRect(pad, paY, paW, paH);                    // left (home goal)
    ctx.strokeRect(W - pad - paW, paY, paW, paH);          // right (away goal)

    // Goal areas
    const gaW = W * 0.07;
    const gaH = H * 0.22;
    const gaY = (H - gaH) / 2;
    ctx.strokeRect(pad, gaY, gaW, gaH);
    ctx.strokeRect(W - pad - gaW, gaY, gaW, gaH);

    // Goals
    const goalH = H * 0.12;
    const goalY = (H - goalH) / 2;
    ctx.strokeRect(0, goalY, pad, goalH);
    ctx.strokeRect(W - pad, goalY, pad, goalH);

    // Team labels
    ctx.font = "bold 9px ui-sans-serif, sans-serif";
    ctx.fillStyle = "rgba(255,255,255,0.35)";
    ctx.textAlign = "center";
    ctx.fillText(homeTeam.slice(0, 10).toUpperCase(), W * 0.25, H - 14);
    ctx.fillText(awayTeam.slice(0, 10).toUpperCase(), W * 0.75, H - 14);

    // ── Heatmap (analyst mode) ────────────────────────────────────────────
    if (showHeatmap && events.length > 0) {
      const heat = ctx.createImageData(W, H);
      for (const ev of events) {
        const px = Math.round((ev.x / 100) * W);
        const py = Math.round((ev.y / 100) * H);
        const r = 18;
        for (let dx = -r; dx <= r; dx++) {
          for (let dy = -r; dy <= r; dy++) {
            const nx = px + dx;
            const ny = py + dy;
            if (nx < 0 || nx >= W || ny < 0 || ny >= H) continue;
            const dist = Math.sqrt(dx * dx + dy * dy);
            if (dist > r) continue;
            const idx = (ny * W + nx) * 4;
            const intensity = Math.round((1 - dist / r) * 60);
            heat.data[idx]     = Math.min(255, heat.data[idx]     + 100);
            heat.data[idx + 1] = Math.min(255, heat.data[idx + 1] + 20);
            heat.data[idx + 2] = Math.min(255, heat.data[idx + 2] + 80);
            heat.data[idx + 3] = Math.min(255, heat.data[idx + 3] + intensity);
          }
        }
      }
      ctx.putImageData(heat, 0, 0);
    }

    // ── Event dots ────────────────────────────────────────────────────────
    const recent = events.slice(-40);
    recent.forEach((ev, i) => {
      const px = (ev.x / 100) * W;
      const py = (ev.y / 100) * H;
      const age = recent.length - i;
      const alpha = Math.max(0.15, 1 - age / 40);

      ctx.globalAlpha = alpha;
      ctx.fillStyle = eventColor(ev.event_type);
      ctx.beginPath();
      ctx.arc(px, py, 3, 0, Math.PI * 2);
      ctx.fill();
    });
    ctx.globalAlpha = 1;

    // ── Ball (latest event position) ──────────────────────────────────────
    if (latestEvent) {
      const bx = (latestEvent.x / 100) * W;
      const by = (latestEvent.y / 100) * H;

      // Glow
      const glow = ctx.createRadialGradient(bx, by, 0, bx, by, 12);
      glow.addColorStop(0,   "rgba(255,255,255,0.4)");
      glow.addColorStop(1,   "rgba(255,255,255,0)");
      ctx.fillStyle = glow;
      ctx.beginPath();
      ctx.arc(bx, by, 12, 0, Math.PI * 2);
      ctx.fill();

      // Ball
      ctx.fillStyle = "#FFFFFF";
      ctx.beginPath();
      ctx.arc(bx, by, 5, 0, Math.PI * 2);
      ctx.fill();
    }
  }, [events, latestEvent, homeTeam, awayTeam, showHeatmap]);

  return (
    <div className={`relative rounded-lg overflow-hidden ${className}`}>
      <canvas
        ref={canvasRef}
        width={480}
        height={300}
        className="w-full h-full"
        aria-label="Pitch visualization showing event locations"
        role="img"
      />
    </div>
  );
}
