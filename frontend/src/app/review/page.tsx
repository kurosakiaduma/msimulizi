"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";

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

interface ReviewData {
  corrections: Correction[];
  latency: LatencyMetric[];
  groundedness_score: number;
  rating_queue_size: number;
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "";

async function fetchReviewData(apiKey: string): Promise<ReviewData> {
  const res = await fetch(`${API_BASE}/v1/review`, {
    headers: { "X-API-Key": apiKey },
  });
  if (res.status === 401 || res.status === 403) {
    throw new Error("Unauthorised");
  }
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<ReviewData>;
}

async function approveCorrection(apiKey: string, id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/v1/corrections/${id}/approve`, {
    method: "POST",
    headers: { "X-API-Key": apiKey },
  });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
}

async function rejectCorrection(apiKey: string, id: string): Promise<void> {
  const res = await fetch(`${API_BASE}/v1/corrections/${id}/reject`, {
    method: "POST",
    headers: { "X-API-Key": apiKey },
  });
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
  const [apiKey, setApiKey] = useState("");
  const [inputKey, setInputKey] = useState("");
  const [data, setData] = useState<ReviewData | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [actionMsg, setActionMsg] = useState<string | null>(null);

  const load = useCallback(async (key: string) => {
    setLoading(true);
    setError(null);
    try {
      const result = await fetchReviewData(key);
      setData(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Unknown error");
      setData(null);
    } finally {
      setLoading(false);
    }
  }, []);

  function handleUnlock(e: React.FormEvent) {
    e.preventDefault();
    const trimmed = inputKey.trim();
    if (!trimmed) return;
    setApiKey(trimmed);
    load(trimmed);
  }

  async function handleApprove(id: string) {
    try {
      await approveCorrection(apiKey, id);
      setActionMsg("Correction approved");
      load(apiKey);
    } catch {
      setActionMsg("Action failed");
    }
  }

  async function handleReject(id: string) {
    try {
      await rejectCorrection(apiKey, id);
      setActionMsg("Correction rejected");
      load(apiKey);
    } catch {
      setActionMsg("Action failed");
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
              </div>
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
