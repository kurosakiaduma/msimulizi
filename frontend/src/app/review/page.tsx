"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { loadRuntimeConfig } from "@/lib/runtimeConfig";

interface Correction {
  id: string;
  card_id: string;
  card_type: string;
  original_sw: string;
  suggested_sw: string;
  submitted_at: string;
  status: "pending" | "approved" | "rejected";
}

interface LatencyMetric {
  label: string;
  p50_ms: number;
  p95_ms: number;
}

interface StoredSwahiliReview {
  id: string;
  reviewer: string;
  fluency: number;
  idiom: number;
  faithfulness: number;
  note: string;
  corrected_headline: string;
  corrected_body: string;
  blocking: boolean;
  requires_second_review: boolean;
  submitted_at: string;
}

interface SwahiliReviewItem {
  id: string;
  card_id: string;
  match_id: string;
  minute: number;
  headline: string;
  body: string;
  gloss_headline: string;
  gloss_body: string;
  source: string;
  review: StoredSwahiliReview | null;
}

interface SwahiliReviewPayload {
  items: SwahiliReviewItem[];
  count: number;
  reviewed: number;
  average: number | null;
  sign_off_required: boolean;
}

interface ReviewData {
  corrections: Correction[];
  latency: LatencyMetric[];
  groundedness_score: number;
  rating_queue_size: number;
  swahili_review: SwahiliReviewPayload;
}

interface ReviewDraft {
  fluency: number;
  idiom: number;
  faithfulness: number;
  note: string;
  correctedHeadline: string;
  correctedBody: string;
  blocking: boolean;
}

function emptyDraft(): ReviewDraft {
  return {
    fluency: 0,
    idiom: 0,
    faithfulness: 0,
    note: "",
    correctedHeadline: "",
    correctedBody: "",
    blocking: false,
  };
}

async function fetchReviewData(apiBase: string, apiKey: string): Promise<ReviewData> {
  const res = await fetch(`${apiBase}/v1/review`, {
    headers: { "X-API-Key": apiKey },
  });
  if (res.status === 401 || res.status === 403) {
    throw new Error("Unauthorised");
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<ReviewData>;
}

async function approveCorrection(apiBase: string, apiKey: string, id: string): Promise<void> {
  const res = await fetch(`${apiBase}/v1/corrections/${id}/approve`, {
    method: "POST",
    headers: { "X-API-Key": apiKey },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

async function rejectCorrection(apiBase: string, apiKey: string, id: string): Promise<void> {
  const res = await fetch(`${apiBase}/v1/corrections/${id}/reject`, {
    method: "POST",
    headers: { "X-API-Key": apiKey },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

async function submitSwahiliReview(
  apiBase: string,
  apiKey: string,
  item: SwahiliReviewItem,
  draft: ReviewDraft,
  reviewer: string
): Promise<void> {
  const res = await fetch(`${apiBase}/v1/review/swahili`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "X-API-Key": apiKey,
    },
    body: JSON.stringify({
      id: item.id,
      card_id: item.card_id,
      match_id: item.match_id,
      headline: item.headline,
      body: item.body,
      gloss_headline: item.gloss_headline,
      gloss_body: item.gloss_body,
      fluency: draft.fluency,
      idiom: draft.idiom,
      faithfulness: draft.faithfulness,
      note: draft.note,
      corrected_headline: draft.correctedHeadline,
      corrected_body: draft.correctedBody,
      reviewer,
      blocking: draft.blocking,
    }),
  });
  if (res.status === 401 || res.status === 403) {
    throw new Error("Unauthorised");
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

function LatencyBar({ p50, p95, max }: { p50: number; p95: number; max: number }) {
  const p50Pct = Math.min((p50 / max) * 100, 100);
  const p95Pct = Math.min((p95 / max) * 100, 100);
  return (
    <div className="relative h-4 rounded bg-[--bg-inset] overflow-hidden" role="img" aria-label={`p50 ${p50}ms p95 ${p95}ms`}>
      <div
        className="absolute inset-y-0 left-0 bg-violet-500/40 rounded"
        style={{ width: `${p95Pct}%` }}
      />
      <div
        className="absolute inset-y-0 left-0 bg-violet-500 rounded"
        style={{ width: `${p50Pct}%` }}
      />
    </div>
  );
}

export default function ReviewPage() {
  const [apiBase, setApiBase] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [inputKey, setInputKey] = useState("");
  const [data, setData] = useState<ReviewData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);
  const [reviewerName, setReviewerName] = useState("");
  const [showAll, setShowAll] = useState(false);
  const [drafts, setDrafts] = useState<Record<string, ReviewDraft>>({});

  useEffect(() => {
    let active = true;
    loadRuntimeConfig().then((config) => {
      if (active) setApiBase(config.backendUrl);
    });
    return () => {
      active = false;
    };
  }, []);

  const load = useCallback(async (key: string) => {
    if (!apiBase) {
      setError("Still loading connection settings; try again.");
      return;
    }

    setLoading(true);
    setError(null);
    try {
      const result = await fetchReviewData(apiBase, key);
      setData(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [apiBase]);

  function handleUnlock(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = inputKey.trim();
    if (!trimmed) return;
    setApiKey(trimmed);
    load(trimmed);
  }

  async function handleApprove(id: string) {
    try {
      await approveCorrection(apiBase, apiKey, id);
      setActionMsg("Correction approved");
      load(apiKey);
    } catch {
      setActionMsg("Action failed");
    }
  }

  async function handleReject(id: string) {
    try {
      await rejectCorrection(apiBase, apiKey, id);
      setActionMsg("Correction rejected");
      load(apiKey);
    } catch {
      setActionMsg("Action failed");
    }
  }

  function updateDraft(itemId: string, patch: Partial<ReviewDraft>) {
    setDrafts((current) => ({
      ...current,
      [itemId]: { ...(current[itemId] ?? emptyDraft()), ...patch },
    }));
  }

  async function handleSwahiliSubmit(item: SwahiliReviewItem) {
    const draft = drafts[item.id] ?? emptyDraft();
    if (!reviewerName.trim()) {
      setActionMsg("Enter the reviewer name first");
      return;
    }
    if (!draft.fluency || !draft.idiom || !draft.faithfulness) {
      setActionMsg("Score fluency, idiom, and faithfulness before submitting");
      return;
    }

    try {
      await submitSwahiliReview(apiBase, apiKey, item, draft, reviewerName.trim());
      setActionMsg("Swahili review recorded");
      setDrafts((current) => {
        const next = { ...current };
        delete next[item.id];
        return next;
      });
      load(apiKey);
    } catch (e) {
      setActionMsg(e instanceof Error ? e.message : "Review failed");
    }
  }

  // Clear action message after 3s
  useEffect(() => {
    if (!actionMsg) return;
    const t = setTimeout(() => setActionMsg(null), 3000);
    return () => clearTimeout(t);
  }, [actionMsg]);

  const maxLatency = data
    ? Math.max(...data.latency.map((l) => l.p95_ms), 1000)
    : 1000;

  const pendingCorrections = data?.corrections.filter((c) => c.status === "pending") ?? [];
  const swahiliReview = data?.swahili_review;
  const reviewItems = swahiliReview?.items ?? [];
  const visibleReviewItems = showAll ? reviewItems : reviewItems.slice(0, 6);
  const unreviewedCount = reviewItems.filter((item) => !item.review).length;

  return (
    <div className="min-h-screen bg-[--bg-base] flex flex-col">
      <header
        className="sticky top-0 z-30 flex items-center justify-between
                   px-4 py-2 bg-[--bg-surface]/90 backdrop-blur-sm
                   border-b border-[--border-subtle]"
        aria-label="Site header"
      >
        <div className="flex items-center gap-3">
          <Link
            href="/"
            className="text-sm font-bold tracking-tight text-[--text-primary]
                       hover:text-violet-400 transition-colors
                       focus-visible:ring-2 focus-visible:ring-violet-500 rounded px-1"
            aria-label="Back to Msimulizi home"
          >
            Msimulizi
          </Link>
          <span className="text-[--text-muted]" aria-hidden="true">/</span>
          <span className="text-[10px] text-[--text-muted] uppercase tracking-wider">
            Review Dashboard
          </span>
        </div>
        <nav aria-label="Site navigation">
          <Link
            href="/about"
            className="text-[11px] text-[--text-muted] hover:text-[--text-primary] transition-colors
                       focus-visible:ring-2 focus-visible:ring-violet-500 px-2 py-1 rounded"
          >
            About
          </Link>
          <Link
            href="/"
            className="text-[11px] text-[--text-muted] hover:text-[--text-primary] transition-colors
                       focus-visible:ring-2 focus-visible:ring-violet-500 px-2 py-1 rounded"
          >
            ← Back to Match
          </Link>
        </nav>
      </header>

      <main
        className="flex-1 max-w-3xl mx-auto w-full px-6 py-10 flex flex-col gap-8"
        id="main-content"
      >
        <h1 className="text-xl font-bold text-[--text-primary]">
          Native-Speaker Review Dashboard
        </h1>

        {/* API key gate */}
        {!apiKey && (
          <section
            aria-labelledby="auth-heading"
            className="rounded-xl border border-[--border-subtle] bg-[--bg-elevated] p-6 flex flex-col gap-4"
          >
            <h2 id="auth-heading" className="text-sm font-semibold text-[--text-primary]">
              Enter API key to continue
            </h2>
            <form onSubmit={handleUnlock} className="flex flex-col gap-3">
              <label
                htmlFor="api-key-input"
                className="text-[10px] uppercase tracking-widest text-[--text-muted]"
              >
                API Key
              </label>
              <div className="flex gap-2">
                <input
                  id="api-key-input"
                  type="password"
                  value={inputKey}
                  onChange={(e) => setInputKey(e.target.value)}
                  placeholder="sk-…"
                  className="flex-1 rounded-md bg-[--bg-inset] border border-[--border-subtle]
                             text-sm text-[--text-primary] placeholder-[--text-muted] px-3 py-2
                             focus:outline-none focus:border-violet-500/60 focus:ring-2
                             focus:ring-violet-500/30"
                  autoComplete="current-password"
                  aria-label="Review API key"
                  required
                />
                <button
                  type="submit"
                  className="px-4 py-2 bg-violet-600 hover:bg-violet-500 text-white text-sm
                             rounded-md transition-colors focus-visible:ring-2
                             focus-visible:ring-violet-500 focus-visible:ring-offset-2
                             focus-visible:ring-offset-[--bg-elevated]"
                >
                  Unlock
                </button>
              </div>
            </form>
            {error && (
              <p className="text-xs text-red-400" role="alert">
                {error === "Unauthorised"
                  ? "Invalid API key — access denied."
                  : `Error: ${error}`}
              </p>
            )}
          </section>
        )}

        {loading && (
          <p className="text-sm text-[--text-muted]" role="status" aria-live="polite">
            Loading…
          </p>
        )}

        {/* Action message */}
        {actionMsg && (
          <p
            className="text-xs text-emerald-400 font-medium"
            role="status"
            aria-live="polite"
          >
            ✓ {actionMsg}
          </p>
        )}

        {data && (
          <>
            {/* ── Summary metrics ─────────────────────────────────── */}
            <section aria-labelledby="metrics-heading">
              <h2
                id="metrics-heading"
                className="text-sm font-semibold text-[--text-primary] mb-4 pb-2
                           border-b border-[--border-subtle]"
              >
                System Metrics
              </h2>
              <div className="grid grid-cols-2 gap-3 sm:grid-cols-3">
                <div
                  className="rounded-lg bg-[--bg-elevated] border border-[--border-subtle] p-3"
                  aria-label={`Groundedness score: ${(data.groundedness_score * 100).toFixed(1)}%`}
                >
                  <p className="text-[9px] uppercase tracking-widest text-[--text-muted] mb-1">
                    Groundedness
                  </p>
                  <p className="text-2xl font-bold text-[--text-primary] tabular-nums">
                    {(data.groundedness_score * 100).toFixed(1)}
                    <span className="text-sm text-[--text-muted] ml-0.5">%</span>
                  </p>
                </div>
                <div
                  className="rounded-lg bg-[--bg-elevated] border border-[--border-subtle] p-3"
                  aria-label={`Rating queue size: ${data.rating_queue_size} items`}
                >
                  <p className="text-[9px] uppercase tracking-widest text-[--text-muted] mb-1">
                    Rating Queue
                  </p>
                  <p className="text-2xl font-bold text-[--text-primary] tabular-nums">
                    {data.rating_queue_size}
                  </p>
                </div>
                <div
                  className="rounded-lg bg-[--bg-elevated] border border-[--border-subtle] p-3"
                  aria-label={`Pending corrections: ${pendingCorrections.length}`}
                >
                  <p className="text-[9px] uppercase tracking-widest text-[--text-muted] mb-1">
                    Pending
                  </p>
                  <p className="text-2xl font-bold text-amber-400 tabular-nums">
                    {pendingCorrections.length}
                  </p>
                </div>
                <div
                  className="rounded-lg bg-[--bg-elevated] border border-[--border-subtle] p-3"
                  aria-label={`Native Swahili reviews: ${swahiliReview?.reviewed ?? 0} of ${swahiliReview?.count ?? 0}, average ${swahiliReview?.average ?? "not yet published"}`}
                >
                  <p className="text-[9px] uppercase tracking-widest text-[--text-muted] mb-1">
                    Swahili Reviews
                  </p>
                  <p className="text-2xl font-bold text-[--text-primary] tabular-nums">
                    {swahiliReview?.reviewed ?? 0}
                    <span className="text-sm text-[--text-muted] ml-0.5">
                      /{swahiliReview?.count ?? 0}
                    </span>
                  </p>
                  <p className="text-[9px] text-[--text-muted]">
                    {swahiliReview?.average !== null && swahiliReview?.average !== undefined
                      ? `${swahiliReview.average.toFixed(1)} / 5 avg`
                      : "No score published"}
                  </p>
                </div>
              </div>
            </section>

            {/* ── Native-speaker queue ─────────────────────────────── */}
            <section aria-labelledby="swahili-heading">
              <div className="flex flex-wrap items-end justify-between gap-3 mb-4 pb-2 border-b border-[--border-subtle]">
                <div>
                  <h2 id="swahili-heading" className="text-sm font-semibold text-[--text-primary]">
                    Native-Speaker Review Queue
                  </h2>
                  <p className="text-[10px] text-[--text-muted] mt-1">
                    Swahili first, English gloss second. Score 1–5; a published
                    average waits for 30 signed-off lines.
                  </p>
                </div>
                <div className="flex items-center gap-2">
                  <label htmlFor="reviewer-name" className="text-[9px] uppercase tracking-widest text-[--text-muted]">
                    Reviewer
                  </label>
                  <input
                    id="reviewer-name"
                    value={reviewerName}
                    onChange={(event) => setReviewerName(event.target.value)}
                    placeholder="Your name"
                    className="w-32 rounded-md bg-[--bg-inset] border border-[--border-subtle]
                               text-xs text-[--text-primary] placeholder-[--text-muted] px-2 py-1
                               focus:outline-none focus:border-violet-500/60 focus:ring-2
                               focus:ring-violet-500/30"
                  />
                </div>
              </div>

              <p className="text-[10px] text-[--text-muted] mb-3" role="status" aria-live="polite">
                {swahiliReview?.sign_off_required
                  ? `${unreviewedCount} line${unreviewedCount === 1 ? "" : "s"} still need review. No rating is claimed yet.`
                  : "The queue has reached the 30-line sign-off threshold."}
              </p>

              {visibleReviewItems.length === 0 ? (
                <p className="text-sm text-[--text-muted]">No Swahili review items are available in this build.</p>
              ) : (
                <ul className="flex flex-col gap-3" aria-label="Swahili review queue">
                  {visibleReviewItems.map((item) => {
                    const draft = drafts[item.id] ?? emptyDraft();
                    return (
                      <li
                        key={item.id}
                        className="rounded-xl border border-[--border-subtle] bg-[--bg-elevated] p-4 flex flex-col gap-3"
                      >
                        <div className="flex flex-wrap items-start justify-between gap-2">
                          <span className="text-[9px] uppercase tracking-widest text-[--text-muted]">
                            Minute {item.minute} · {item.source}
                          </span>
                          {item.review ? (
                            <span className="text-[9px] px-2 py-0.5 rounded-full bg-emerald-500/15 text-emerald-400">
                              Reviewed by {item.review.reviewer || "unnamed"} ·{" "}
                              {((item.review.fluency + item.review.idiom + item.review.faithfulness) / 3).toFixed(1)}/5
                            </span>
                          ) : (
                            <span className="text-[9px] px-2 py-0.5 rounded-full bg-amber-500/15 text-amber-400">
                              Pending
                            </span>
                          )}
                        </div>

                        <div className="grid gap-2 sm:grid-cols-2">
                          <div>
                            <p className="text-[9px] uppercase tracking-widest text-[--text-muted] mb-1">Swahili</p>
                            <p className="text-sm text-[--text-primary] leading-relaxed">{item.headline}</p>
                            <p className="text-xs text-[--text-secondary] leading-relaxed mt-1">{item.body}</p>
                          </div>
                          <div>
                            <p className="text-[9px] uppercase tracking-widest text-[--text-muted] mb-1">English gloss</p>
                            <p className="text-xs text-[--text-secondary] leading-relaxed">{item.gloss_headline}</p>
                            <p className="text-xs text-[--text-muted] leading-relaxed mt-1">{item.gloss_body}</p>
                          </div>
                        </div>

                        {item.review ? (
                          <div className="text-[10px] text-[--text-muted]">
                            {item.review.note || "No note recorded."}
                            {item.review.requires_second_review && (
                              <span className="ml-2 text-amber-400">Second reviewer required (edited line).</span>
                            )}
                          </div>
                        ) : (
                          <div className="flex flex-col gap-2">
                            <div className="grid gap-2 sm:grid-cols-3">
                              {([
                                ["fluency", "Fluency"],
                                ["idiom", "Idiom / register"],
                                ["faithfulness", "Faithfulness"],
                              ] as const).map(([key, label]) => (
                                <label key={key} className="flex flex-col gap-1 text-[9px] uppercase tracking-widest text-[--text-muted]">
                                  {label}
                                  <select
                                    value={draft[key]}
                                    onChange={(event) => updateDraft(item.id, { [key]: Number(event.target.value) })}
                                    className="rounded-md bg-[--bg-inset] border border-[--border-subtle]
                                               text-xs text-[--text-primary] px-2 py-1
                                               focus:outline-none focus:border-violet-500/60 focus:ring-2
                                               focus:ring-violet-500/30"
                                  >
                                    <option value={0}>—</option>
                                    {[1, 2, 3, 4, 5].map((score) => (
                                      <option key={score} value={score}>{score}</option>
                                    ))}
                                  </select>
                                </label>
                              ))}
                            </div>

                            <div className="grid gap-2 sm:grid-cols-2">
                              <label className="flex flex-col gap-1 text-[9px] uppercase tracking-widest text-[--text-muted]">
                                Corrected headline (optional)
                                <input
                                  value={draft.correctedHeadline}
                                  onChange={(event) => updateDraft(item.id, { correctedHeadline: event.target.value })}
                                  className="rounded-md bg-[--bg-inset] border border-[--border-subtle]
                                             text-xs text-[--text-primary] px-2 py-1
                                             focus:outline-none focus:border-violet-500/60 focus:ring-2
                                             focus:ring-violet-500/30"
                                />
                              </label>
                              <label className="flex flex-col gap-1 text-[9px] uppercase tracking-widest text-[--text-muted]">
                                Corrected body (optional)
                                <input
                                  value={draft.correctedBody}
                                  onChange={(event) => updateDraft(item.id, { correctedBody: event.target.value })}
                                  className="rounded-md bg-[--bg-inset] border border-[--border-subtle]
                                             text-xs text-[--text-primary] px-2 py-1
                                             focus:outline-none focus:border-violet-500/60 focus:ring-2
                                             focus:ring-violet-500/30"
                                />
                              </label>
                            </div>

                            <label className="flex flex-col gap-1 text-[9px] uppercase tracking-widest text-[--text-muted]">
                              Note / blocking issue
                              <textarea
                                value={draft.note}
                                onChange={(event) => updateDraft(item.id, { note: event.target.value })}
                                rows={2}
                                className="rounded-md bg-[--bg-inset] border border-[--border-subtle]
                                           text-xs text-[--text-primary] px-2 py-1 resize-y
                                           focus:outline-none focus:border-violet-500/60 focus:ring-2
                                           focus:ring-violet-500/30"
                              />
                            </label>

                            <div className="flex flex-wrap items-center justify-between gap-2">
                              <label className="flex items-center gap-2 text-[10px] text-[--text-muted]">
                                <input
                                  type="checkbox"
                                  checked={draft.blocking}
                                  onChange={(event) => updateDraft(item.id, { blocking: event.target.checked })}
                                />
                                Blocking issue (fact, safety, missing gloss)
                              </label>
                              <button
                                type="button"
                                onClick={() => handleSwahiliSubmit(item)}
                                className="text-[11px] px-3 py-1 bg-violet-600 hover:bg-violet-500
                                           text-white rounded-md transition-colors
                                           focus-visible:ring-2 focus-visible:ring-violet-500
                                           focus-visible:ring-offset-2 focus-visible:ring-offset-[--bg-elevated]"
                              >
                                Submit review
                              </button>
                            </div>
                          </div>
                        )}
                      </li>
                    );
                  })}
                </ul>
              )}

              {reviewItems.length > 6 && (
                <button
                  type="button"
                  onClick={() => setShowAll((current) => !current)}
                  className="mt-3 text-[11px] px-3 py-1 border border-[--border-subtle]
                             rounded-md text-[--text-secondary] hover:text-[--text-primary]
                             focus-visible:ring-2 focus-visible:ring-violet-500"
                >
                  {showAll ? "Show fewer" : `Show all ${reviewItems.length} lines`}
                </button>
              )}
            </section>

            {/* ── Latency charts ───────────────────────────────────── */}
            <section aria-labelledby="latency-heading">
              <h2
                id="latency-heading"
                className="text-sm font-semibold text-[--text-primary] mb-4 pb-2
                           border-b border-[--border-subtle]"
              >
                Latency (p50 / p95)
              </h2>
              <div
                className="flex flex-col gap-3"
                role="list"
                aria-label="Latency metrics by pipeline stage"
              >
                {data.latency.map((l) => (
                  <div key={l.label} className="flex flex-col gap-1" role="listitem">
                    <div className="flex items-center justify-between text-[11px]">
                      <span className="text-[--text-secondary] font-medium">{l.label}</span>
                      <span className="font-mono text-[--text-muted] tabular-nums">
                        <span className="text-violet-400">{l.p50_ms}</span>
                        <span className="text-[--text-muted] mx-1">/</span>
                        <span>{l.p95_ms}</span>
                        <span className="ml-1 text-[--text-muted]">ms</span>
                      </span>
                    </div>
                    <LatencyBar p50={l.p50_ms} p95={l.p95_ms} max={maxLatency} />
                  </div>
                ))}
              </div>
              <p className="mt-2 text-[9px] text-[--text-muted]">
                Purple bar = p50 · translucent = p95
              </p>
            </section>

            {/* ── Correction queue ─────────────────────────────────── */}
            <section aria-labelledby="corrections-heading">
              <h2
                id="corrections-heading"
                className="text-sm font-semibold text-[--text-primary] mb-4 pb-2
                           border-b border-[--border-subtle]"
              >
                Correction Queue
              </h2>
              {pendingCorrections.length === 0 ? (
                <p className="text-sm text-[--text-muted]">No pending corrections.</p>
              ) : (
                <ul className="flex flex-col gap-3" aria-label="Pending corrections list">
                  {pendingCorrections.map((c) => (
                    <li
                      key={c.id}
                      className="rounded-xl border border-[--border-subtle] bg-[--bg-elevated] p-4
                                 flex flex-col gap-3"
                    >
                      <div className="flex items-start justify-between gap-2">
                        <div className="flex flex-col gap-1 flex-1 min-w-0">
                          <span className="text-[9px] uppercase tracking-widest text-[--text-muted]">
                            Original
                          </span>
                          <p className="text-xs text-[--text-secondary] leading-relaxed">
                            {c.original_sw}
                          </p>
                          <span className="text-[9px] uppercase tracking-widest text-amber-400/70 mt-1">
                            Suggested
                          </span>
                          <p className="text-xs text-[--text-primary] leading-relaxed">
                            {c.suggested_sw}
                          </p>
                        </div>
                        <span className="shrink-0 text-[9px] font-mono text-[--text-muted]">
                          {new Date(c.submitted_at).toLocaleDateString()}
                        </span>
                      </div>

                      <div
                        className="flex gap-2"
                        role="group"
                        aria-label={`Actions for correction ${c.id}`}
                      >
                        <button
                          onClick={() => handleApprove(c.id)}
                          className="text-[11px] px-3 py-1 bg-emerald-600 hover:bg-emerald-500
                                     text-white rounded-md transition-colors
                                     focus-visible:ring-2 focus-visible:ring-emerald-500
                                     focus-visible:ring-offset-2 focus-visible:ring-offset-[--bg-elevated]"
                          aria-label={`Approve correction ${c.id}`}
                        >
                          Approve
                        </button>
                        <button
                          onClick={() => handleReject(c.id)}
                          className="text-[11px] px-3 py-1 bg-red-600/80 hover:bg-red-500
                                     text-white rounded-md transition-colors
                                     focus-visible:ring-2 focus-visible:ring-red-500
                                     focus-visible:ring-offset-2 focus-visible:ring-offset-[--bg-elevated]"
                          aria-label={`Reject correction ${c.id}`}
                        >
                          Reject
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </>
        )}
      </main>
    </div>
  );
}
