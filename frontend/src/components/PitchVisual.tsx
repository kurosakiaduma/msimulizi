"use client";

import { useEffect, useRef, useState } from "react";
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

const EVENT_LABEL: Record<string, string> = {
  shot:         "Shot",
  goal:         "Goal",
  pass:         "Pass",
  tackle:       "Tackle",
  interception: "Interception",
  foul:         "Foul",
  card:         "Card",
};

export function PitchVisual({
  events,
  latestEvent,
  homeTeam,
  awayTeam,
  showHeatmap = false,
  className = "",
}: Props) {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [hovered, setHovered] = useState<EventDot | null>(null);

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
    // Add translucent radial gradients over the drawn pitch. The previous
    // implementation wrote a full-canvas ImageData buffer, which replaced the
    // pitch pixels (and their alpha) with mostly transparent black — that is
    // why analyst mode showed only dots on a black rectangle.
    if (showHeatmap && events.length > 0) {
      ctx.save();
      ctx.globalCompositeOperation = "lighter";
      const radius = Math.max(18, Math.min(W, H) * 0.075);
      for (const ev of events) {
        const px = (ev.x / 100) * W;
        const py = (ev.y / 100) * H;
        const glow = ctx.createRadialGradient(px, py, 0, px, py, radius);
        glow.addColorStop(0, "rgba(124, 58, 237, 0.20)");
        glow.addColorStop(0.55, "rgba(245, 158, 11, 0.08)");
        glow.addColorStop(1, "rgba(124, 58, 237, 0)");
        ctx.fillStyle = glow;
        ctx.beginPath();
        ctx.arc(px, py, radius, 0, Math.PI * 2);
        ctx.fill();
      }
      ctx.restore();
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

      {/* Hover targets + tooltips over each event dot (canvas is drawn beneath) */}
      {events.slice(-40).map((ev, i) => {
        const age = events.slice(-40).length - i;
        const alpha = Math.max(0.15, 1 - age / 40);
        const size = Math.max(10, 12 / alpha); // hit target matches visual dot size
        const label = EVENT_LABEL[ev.event_type] ?? ev.event_type;
        const minuteLabel = ev.minute ? `′` : "";
        return (
          <button
            key={ev.event_id ?? i}
            type="button"
            aria-label={`${label} at minute ${ev.minute}${minuteLabel}`}
            onMouseEnter={() => setHovered(ev)}
            onMouseLeave={() => setHovered(null)}
            style={{
              position: "absolute",
              left: `${ev.x}%`,
              top: `${ev.y}%`,
              transform: "translate(-50%, -50%)",
              width: size,
              height: size,
              background: "transparent",
              border: "none",
              cursor: "pointer",
              padding: 0,
              zIndex: 10,
            }}
          />
        );
      })}

      {/* Tooltip for hovered marker */}
      {hovered && (
        <div
          className="pointer-events-none absolute z-20 bg-[--bg-surface]
                     border border-[--border-subtle] rounded-md px-2 py-1
                     text-[10px] text-[--text-primary] shadow-lg whitespace-nowrap"
          style={{
            left: `${hovered.x}%`,
            top: `${hovered.y}%`,
            transform: "translate(10px, -130%)",
          }}
        >
          {EVENT_LABEL[hovered.event_type] ?? hovered.event_type}{" "}
          {hovered.minute ? `${hovered.minute}′` : ""}{" "}
          {hovered.player ? `— ${hovered.player}` : ""}
        </div>
      )}

      {/* Event-type legend */}
      <div className="absolute top-2 left-2 z-20 flex flex-wrap gap-2 px-2">
        {Object.entries(EVENT_LABEL).map(([type, label]) => (
          <button
            key={type}
            type="button"
            className="flex items-center gap-1.5 rounded border border-[--border-subtle]
                       bg-[--bg-surface]/90 px-1.5 py-0.5 text-[9px]
                       text-[--text-muted] hover:text-[--text-primary]
                       transition-colors"
            style={{ borderLeft: `3px solid ${eventColor(type)}` }}
            aria-label={label}
          >
            <span className="w-1.5 h-1.5 rounded-full" style={{ backgroundColor: eventColor(type) }} />
            {label}
          </button>
        ))}
      </div>
    </div>
  );
}
