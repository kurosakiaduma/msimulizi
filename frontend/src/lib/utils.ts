import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}

/** Format match clock as "mm:ss" */
export function formatClock(minute: number, second: number): string {
  return `${String(minute).padStart(2, "0")}:${String(second).padStart(2, "0")}`;
}

/** Map card_type to a display label */
export const CARD_TYPE_LABEL: Record<string, string> = {
  goal: "Goal",
  key_moment: "Key Moment",
  stat: "Stat",
  player_spotlight: "Spotlight",
  recap: "Recap",
};

/** Map card_type to Tailwind colour token (border/text) */
export const CARD_TYPE_COLOR: Record<string, string> = {
  goal: "text-amber-400 border-amber-400/40",
  key_moment: "text-violet-400 border-violet-400/40",
  stat: "text-blue-400 border-blue-400/40",
  player_spotlight: "text-emerald-400 border-emerald-400/40",
  recap: "text-purple-400 border-purple-400/40",
};

export const CARD_TYPE_BG: Record<string, string> = {
  goal: "bg-amber-400/10",
  key_moment: "bg-violet-400/10",
  stat: "bg-blue-400/10",
  player_spotlight: "bg-emerald-400/10",
  recap: "bg-purple-400/10",
};
