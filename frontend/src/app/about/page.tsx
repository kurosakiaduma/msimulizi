import type { Metadata } from "next";
import Link from "next/link";

export const metadata: Metadata = {
  title: "About — Msimulizi",
  description: "Data provenance, AI disclosure, and attributions for Msimulizi.",
};

export default function AboutPage() {
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
          <span className="text-[10px] text-[--text-muted] uppercase tracking-wider">About</span>
        </div>
        <nav aria-label="Site navigation">
          <Link
            href="/review"
            className="text-[11px] text-[--text-muted] hover:text-[--text-primary] transition-colors
                       focus-visible:ring-2 focus-visible:ring-violet-500 px-2 py-1 rounded"
          >
            Review Dashboard
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
        className="flex-1 max-w-2xl mx-auto w-full px-6 py-10 flex flex-col gap-10"
        id="main-content"
      >
        {/* ── Project overview ──────────────────────────────────── */}
        <section aria-labelledby="about-heading">
          <h1
            id="about-heading"
            className="text-xl font-bold text-[--text-primary] mb-3"
          >
            Msimulizi — AI Match Intelligence
          </h1>
          <p className="text-sm leading-relaxed text-[--text-secondary]">
            Msimulizi (Swahili for &ldquo;the narrator&rdquo;) is a real-time match
            intelligence platform that transforms synthetic football event streams
            into live, explainable commentary and overlay cards in Swahili, English,
            and French, powered by Microsoft Azure AI.
          </p>
        </section>

        {/* ── Data provenance ───────────────────────────────────── */}
        <section aria-labelledby="data-provenance-heading">
          <h2
            id="data-provenance-heading"
            className="text-base font-semibold text-[--text-primary] mb-3 pb-2
                       border-b border-[--border-subtle]"
          >
            Data Provenance
          </h2>
          <div className="flex flex-col gap-3 text-sm text-[--text-secondary] leading-relaxed">
            <p>
              All match data used in this system is{" "}
              <strong className="text-[--text-primary]">
                entirely synthetic and newly generated
              </strong>{" "}
              within the hackathon submission window. No real football match
              data, footage, or pre-existing code or model files are used.
            </p>
            <p>
              The xG (Expected Goals) model is a logistic regression trained
              from scratch during the hackathon window on aggregate statistics
              derived from open data sources. Input features: shot distance,
              angle, header flag, and penalty flag. No Premier League data was
              used. No raw data was committed to the repository.
            </p>
            <p>
              Calibration aggregates (pass completion by pitch zone, shot
              conversion by distance and angle, events per minute, pressure
              rates) were computed from permitted open data sources and stored
              as summary statistics only. Raw files were deleted after
              aggregation.
            </p>
            <p>
              All club and player names are fictional. Any resemblance to
              real-world professional football players or clubs, past or
              present, is coincidental.
            </p>
            <p>
              Full details are in{" "}
              <code className="text-violet-400 text-xs bg-[--bg-inset] px-1 py-0.5 rounded">
                DATA_PROVENANCE.md
              </code>{" "}
              in the repository.
            </p>
          </div>
        </section>

        {/* ── StatsBomb attribution ────────────────────────────── */}
        <section aria-labelledby="attribution-heading">
          <h2
            id="attribution-heading"
            className="text-base font-semibold text-[--text-primary] mb-3 pb-2
                       border-b border-[--border-subtle]"
          >
            Data Attribution
          </h2>
          <div className="flex flex-col gap-3 text-sm text-[--text-secondary] leading-relaxed">
            <p>
              Calibration aggregates were derived from open data provided by{" "}
              <strong className="text-[--text-primary]">StatsBomb</strong> under
              their open data license. StatsBomb is acknowledged as the source
              of aggregate statistics used for calibration only; no raw StatsBomb
              data is stored in or distributed with this repository.
            </p>
            <p>
              StatsBomb Open Data is available at{" "}
              <a
                href="https://github.com/statsbomb/open-data"
                className="text-violet-400 hover:text-violet-300 underline underline-offset-2
                           transition-colors focus-visible:ring-2 focus-visible:ring-violet-500 rounded"
                target="_blank"
                rel="noopener noreferrer"
                aria-label="StatsBomb Open Data repository (opens in new tab)"
              >
                github.com/statsbomb/open-data
              </a>
              .
            </p>
          </div>
        </section>

        {/* ── AI disclosure ─────────────────────────────────────── */}
        <section aria-labelledby="ai-disclosure-heading">
          <h2
            id="ai-disclosure-heading"
            className="text-base font-semibold text-[--text-primary] mb-3 pb-2
                       border-b border-[--border-subtle]"
          >
            AI Disclosure
          </h2>
          <div className="flex flex-col gap-3 text-sm text-[--text-secondary] leading-relaxed">
            <p>
              All commentary and overlay cards produced by this system are{" "}
              <strong className="text-[--text-primary]">
                synthetic and AI-generated
              </strong>
              . Every card is labelled accordingly in the interface.
            </p>
            <p>
              Narration is generated by large language models hosted on{" "}
              <strong className="text-[--text-primary]">Microsoft Foundry</strong>{" "}
              (gpt-5.4 and gpt-5.4-mini). Every generated narration line is
              verified for groundedness before delivery: a deterministic
              pre-check validates all factual claims, and an LLM-backed Verifier
              Agent confirms semantic consistency with the underlying evidence.
            </p>
            <p>
              When verification fails twice or a model call times out, the
              system falls back to deterministic template-based narration and
              labels the card accordingly. Pre-generated bundle cards are
              labelled{" "}
              <span className="text-amber-400/80 font-medium">BUNDLE</span>.
            </p>
            <p>
              Audio is synthesised by{" "}
              <strong className="text-[--text-primary]">Azure AI Speech</strong>{" "}
              using neural voices including Swahili (sw-KE / sw-TZ), English,
              and French.
            </p>
            <p>
              Viewers can submit corrections via the thumbs-up / thumbs-down
              controls on each card. Text corrections enter a review queue and
              are incorporated into the Narrator&#39;s few-shot set only after an
              authorised reviewer approves them and Azure AI Content Safety
              clears the edited text.
            </p>
          </div>
        </section>

        {/* ── Azure technologies ───────────────────────────────── */}
        <section aria-labelledby="tech-heading">
          <h2
            id="tech-heading"
            className="text-base font-semibold text-[--text-primary] mb-3 pb-2
                       border-b border-[--border-subtle]"
          >
            Azure Technologies Used
          </h2>
          <ul
            className="flex flex-col gap-1.5 text-sm text-[--text-secondary]"
            aria-label="List of Azure technologies"
          >
            {[
              "Microsoft Foundry — model hosting and evaluation (gpt-5.4, gpt-5.4-mini)",
              "Microsoft Agent Framework — workflow facade for the six-stage commentary pipeline",
              "Azure AI Speech — neural TTS in Swahili, English, and French",
              "Azure AI Content Safety — content moderation for all generated text",
              "Azure Cosmos DB — six containers for state, moments, cache, cards, audit, corrections",
              "Azure Blob Storage — public-read audio storage",
              "Azure Container Apps — backend and frontend hosting",
              "Azure Key Vault — secret management via managed identity",
              "Azure Monitor / Application Insights — latency metrics and the reviewer dashboard",
              "Event-source adapters — in-process, file replay, and Event Hubs-shaped ingestion",
              "Azure Consumption budget — monthly cost guardrail with operator alerts",
            ].map((tech) => (
              <li key={tech} className="flex gap-2 items-start leading-relaxed">
                <span className="text-violet-400 mt-0.5" aria-hidden="true">▸</span>
                <span>{tech}</span>
              </li>
            ))}
          </ul>
        </section>

        <footer className="pt-6 border-t border-[--border-subtle] text-[10px] text-[--text-muted]">
          <p>
            Built for the Microsoft AI Hackathon · All match data is synthetic ·
            No real match footage or licensed data used
          </p>
        </footer>
      </main>
    </div>
  );
}
