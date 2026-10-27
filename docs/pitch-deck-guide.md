# Msimulizi — Pitch Deck Guide

Target: Innovation Studio submission + any supporting slide deck.
Tone: confident, data-driven, story-first. Let the product do the talking.

---

## Colour palette

| Role              | Hex       | Usage                                      |
|-------------------|-----------|--------------------------------------------|
| Background base   | `#0a0a0f` | Slide / page background                    |
| Surface elevated  | `#16161e` | Card backgrounds, panels                   |
| Accent primary    | `#7c3aed` | Violet — CTA buttons, chart bars, headline highlights |
| Accent secondary  | `#06b6d4` | Cyan — data callouts, secondary metrics    |
| Text primary      | `#f4f4f5` | Main body copy                             |
| Text muted        | `#71717a` | Captions, labels                           |
| Pass / success    | `#10b981` | Emerald — verdict pass, positive metrics   |
| Fail / warn       | `#f59e0b` | Amber — fallback count, warnings           |
| Critical          | `#ef4444` | Red card, quota exceeded                   |

Use the violet → cyan diagonal gradient as a hero accent bar or background stripe on section-break slides. Keep body slides dark with white text — the UI is dark-mode only so slides should match.

---

## Typography

- Headlines: **Inter Bold** or **Geist Bold** — same font as the UI
- Body / captions: Inter Regular, 14–16 pt
- Monospace callouts (metric values, scores): **JetBrains Mono** or **Geist Mono**
- Keep slide text minimal — one idea per slide, data in big numbers

---

## Slide structure (8–10 slides max)

### 1. Hook (1 slide)
One sentence, huge font:

> **"Every football moment, told in the fan's language — in real time."**

Background: a dark screenshot of the live overlay card UI with a Swahili narration card visible.

### 2. The problem (1 slide)
- 1.5 billion football fans globally; most commentary is English-only
- African football fans — 400 M+ — have no native-language AI commentary
- Existing broadcast tools are static; no personalisation, no explainability

Use 3 short bullets max. No walls of text.

### 3. The solution (1 slide)
**Msimulizi** = Swahili for "The Narrator"

- Real-time AI overlay cards: Swahili · English · French
- Grounded in match data — every claim cited, every number sourced
- Personalised by club, player, mode (casual / analyst), audio-only

Show a single overlay card screenshot — Swahili headline with English gloss below.

### 4. How it works (1 architecture slide)
Use one of the two available diagram formats:

**Option A — Mermaid (quick):** The README contains a rendered Mermaid graph. Take a screenshot from GitHub's rendered view (dark mode) and drop it directly into the slide.

**Option B — Eraser.io (polished):** Open [`docs/architecture-eraser-spec.md`](architecture-eraser-spec.md), paste the diagram-as-code block into [eraser.io](https://app.eraser.io) → New Diagram → Cloud Architecture, set theme to **Dark**, export as PNG 2×. This gives you the clean isometric Azure icons that look great on a pitch slide.

Either way, label each layer with the Azure service it runs on:

```
Event stream → Intelligence pipeline → Renderer → API / WebSocket → Viewer UI
```

Label each layer with the Azure service it runs on:
- Pipeline → **Azure AI Foundry** (GPT-4o)
- TTS → **Azure AI Speech** (sw-KE-ZuriNeural)
- Safety → **Azure AI Content Safety**
- State → **Azure Cosmos DB**
- Metrics → **Application Insights**
- Hosting → **Azure Container Apps**

### 5. Live demo screenshot (1–2 slides)
Full-width screenshots of:
- The main viewer page: score bar, pitch visual, overlay card in Swahili with gloss
- The personalisation panel open showing language / club / player controls
- (Optional) The `/review` dashboard showing the latency p50/p95 bars and groundedness score

### 6. Quality numbers (1 slide)
Big numbers, one per row:

| | |
|---|---|
| **100%** | Groundedness score (50-entry heuristic eval) |
| **Pending** | Native-speaker Swahili review (30-line sign-off required) |
| **≤ 5 s p50** | Card latency target |
| **≤ 10 s p95** | Card latency target |
| **≥ 90%** | Verifier pass rate target |

Use the emerald colour for the scores.

### 7. Microsoft / Azure technologies used (1 slide)
List every service. Judges check this explicitly:

- Azure AI Foundry — GPT-4o narrator, explainer, verifier (structured output)
- Azure AI Speech — Swahili (sw-KE, sw-TZ), English, French TTS
- Azure AI Content Safety — narration and correction moderation
- Azure Cosmos DB — match state, narration cache, audit log, corrections
- Azure Container Apps — backend API + frontend hosting
- Azure Blob Storage — audio file CDN
- Azure Key Vault — API key management
- Azure Application Insights — OpenTelemetry metrics (card + audio latency, verdict counts)
- Microsoft Agent Framework — six-agent pipeline orchestration

### 8. Innovation angle (1 slide)
Three bullets:

- **Synthetic data innovation**: fully fictional clubs and players; calibrated from StatsBomb open aggregate statistics; no real match data stored
- **Explainability by design**: every AI claim is cited with a source `display_value`; verifier rejects hallucinated numbers
- **African language AI**: Swahili-first pipeline with native-speaker review loop and few-shot corpus; gloss_en for every Swahili card

### 9. Submission checklist / call to action (1 slide)
- Public GitHub repo ✓
- Demo video ✓
- MIT licence ✓
- No personal data, no third-party trademarks ✓

End with the repo URL and a QR code linking to the live demo.

---

## Pitch text for Innovation Studio (copy-paste template)

**Project name:** Msimulizi — AI Match Intelligence

**What it does:**
Msimulizi is a real-time football match intelligence system that transforms a synthetic event stream into live, explainable overlay cards in Swahili, English, and French. A six-agent AI pipeline — built on Microsoft Agent Framework and Azure AI Foundry — narrates every key moment, cites its reasoning, and personalises commentary by club allegiance, mode (casual or analyst), and language. Audio is synthesised with Azure AI Speech using native Swahili voices (sw-KE-ZuriNeural, sw-TZ-RehemaNeural) and delivered over WebSocket to a Next.js viewer UI.

**Problem it solves:**
Over 400 million African football fans have no access to real-time AI commentary in their native language. Existing broadcast tools are English-only, static, and opaque. Msimulizi democratises match intelligence with a grounded, auditable, multilingual AI narrator.

**Microsoft / Azure technologies used:**
Azure AI Foundry (GPT-4o structured output), Azure AI Speech (Swahili TTS), Azure AI Content Safety, Azure Cosmos DB, Azure Container Apps, Azure Blob Storage, Azure Key Vault, Azure Application Insights (OpenTelemetry), Microsoft Agent Framework.

**Areas:**
Real-time intelligence · Explainability · Synthetic data innovation · Narrative generation · Multi-language storytelling
