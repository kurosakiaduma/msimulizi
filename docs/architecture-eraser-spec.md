# Msimulizi — Architecture Diagram (Eraser.io Spec)

This is the compact **pitch-deck export** for the live demo. The complete,
component-by-component Eraser schema is in
[`architecture-eraser-schema.md`](architecture-eraser-schema.md); use that for a
new diagram. This smaller block is kept for existing slide links and quick
edits.

It is aligned with the full Mermaid diagram set in
[`architecture.md`](architecture.md): system context, container view, backend
pipeline and fallbacks, frontend flow, persistence, Azure infrastructure,
observability, live sequence, deployment, and current constraints.

Paste the block below into [eraser.io](https://app.eraser.io) → New Diagram →
Cloud Architecture. Recommended theme: **Dark**. Export as PNG at 2× for the
pitch deck. The current full export is
[`architecture-overview.png`](architecture-overview.png); this compact block is
kept for existing slide links.

---

## Eraser.io diagram-as-code

```
// Msimulizi — AI Match Intelligence
// Theme: dark  |  Layout: left-to-right
// Last synced with docs/architecture.md: 27 Oct 2026

// ── Colour tokens ──────────────────────────────────────────────
// violet  = #7c3aed   (pipeline / AI services)
// cyan    = #06b6d4   (API / exposure)
// emerald = #10b981   (frontend / UI)
// slate   = #334155   (infrastructure)
// amber   = #f59e0b   (storage / observability)

// ── Actors ─────────────────────────────────────────────────────
group Actors [Actors] {
  color: slate
  Viewer [icon: user, label: "Viewer / judge", color: slate]
  Reviewer [icon: check-square, label: "Swahili\nreviewer", color: slate]
  Operator [icon: settings, label: "Operator", color: slate]
  Developer [icon: code, label: "Developer", color: slate]
}

// ── Frontend ───────────────────────────────────────────────────
group Frontend [Next.js frontend Container App] {
  color: emerald
  ViewerUI [icon: layout, label: "Viewer\n/ , /about", color: emerald]
  RuntimeConfig [icon: settings, label: "/api/config\nruntime URLs", color: emerald]
  ReviewUI [icon: bar-chart-2, label: "/review\nreviewer dashboard", color: emerald]
}

// ── Backend ────────────────────────────────────────────────────
group Backend [FastAPI backend Container App — one replica] {
  color: cyan
  REST [icon: server, label: "REST\n/v1 + /health", color: cyan]
  WS [icon: radio, label: "WebSocket\n/ws", color: cyan]
  MCP [icon: terminal, label: "MCP\n/mcp/ + bearer auth", color: cyan]
  Session [icon: users, label: "SessionManager\n+ pipeline tasks", color: cyan]
  Audio [icon: volume-2, label: "AudioService\ncache + TTS", color: cyan]
  InMemory [icon: database, label: "In-memory state\nPubSub + caches", color: cyan]
}

// ── Pipeline ───────────────────────────────────────────────────
group Pipeline [Six-stage commentary pipeline] {
  color: violet
  Interpreter [icon: activity, label: "Interpreter", color: violet]
  Moment [icon: zap, label: "Moment", color: violet]
  Personaliser [icon: user, label: "Personaliser", color: violet]
  Explainer [icon: book-open, label: "Explainer", color: violet]
  Narrator [icon: message-square, label: "Narrator", color: violet]
  Verifier [icon: check-circle, label: "Verifier", color: violet]
  Renderer [icon: layers, label: "Renderer\n+ fallback", color: violet]
}

// ── Azure AI ───────────────────────────────────────────────────
group AIServices [Azure AI services] {
  color: violet
  Foundry [icon: azure-openai, label: "Microsoft Foundry\ngpt-5.4 / gpt-5.4-mini", color: violet]
  Speech [icon: azure-cognitive-services, label: "Azure AI Speech\nsw-KE · sw-TZ · en · fr", color: violet]
  Safety [icon: shield, label: "Azure AI\nContent Safety", color: violet]
}

// ── Data and state ─────────────────────────────────────────────
group DataLayer [Data and state] {
  color: amber
  Cosmos [icon: azure-cosmos-db, label: "Cosmos DB\n6 containers", color: amber]
  Blob [icon: azure-blob-storage, label: "Blob Storage\naudio container", color: amber]
  KeyVault [icon: azure-key-vault, label: "Key Vault\nMCP + reviewer keys", color: amber]
}

// ── Observability and cost ─────────────────────────────────────
group Observability [Observability and cost] {
  color: slate
  AppInsights [icon: azure-monitor, label: "Application Insights\nOTel metrics", color: slate]
  LogAnalytics [icon: file-text, label: "Log Analytics\n30-day logs", color: slate]
  Budget [icon: dollar-sign, label: "Monthly budget\n50/80/100 alerts", color: slate]
}

// ── Delivery ───────────────────────────────────────────────────
group Delivery [Read-only CI and manual delivery] {
  color: slate
  CI [icon: github, label: "GitHub Actions\ntests/checks only", color: slate]
  ACR [icon: azure-container-registry, label: "ACR\nimages", color: slate]
  Revision [icon: box, label: "Container Apps\nrevision", color: slate]
}

// ── Connections ────────────────────────────────────────────────
Viewer --> ViewerUI
Reviewer --> ReviewUI
Developer --> CI

ViewerUI --> REST
ViewerUI --> WS
ViewerUI --> MCP
ViewerUI --> RuntimeConfig
ReviewUI --> REST

REST --> Session
Session --> Interpreter
Interpreter --> Moment
Moment --> Personaliser
Personaliser --> Explainer
Explainer --> Narrator
Narrator --> Verifier
Verifier --> Renderer

Personaliser --> Renderer
Verifier --> Narrator
Verifier --> Renderer

Renderer --> WS
Renderer --> Cosmos
Renderer --> Audio
Renderer --> InMemory

Explainer --> Foundry
Narrator --> Foundry
Verifier --> Foundry
Verifier --> Safety
Audio --> Foundry
Audio --> Speech
Audio --> Blob
Audio --> WS

MCP --> Cosmos
MCP --> InMemory
REST --> Cosmos
REST --> InMemory
Session --> InMemory

KeyVault --> REST
Renderer --> AppInsights
Audio --> AppInsights
REST --> LogAnalytics
Audio --> LogAnalytics
AppInsights --> LogAnalytics

ACR --> Revision
Revision --> ViewerUI
Revision --> REST
Operator --> ACR
Operator --> Revision
Operator --> Budget
```

---

## What the pitch slide should show

- **Captions are primary, audio is an enhancement.** The Renderer broadcasts a
  verified card before the Audio branch runs.
- **Grounding is explicit.** Verifier checks numbers, claims, evidence, and
  Content Safety; failures take the fallback path.
- **Persistence is real.** Cosmos DB holds snapshots, moments, narration cache,
  overlay cards, audit entries, and corrections.
- **The backend is intentionally one replica.** Active sessions and WebSockets
  are process-local until a shared backplane exists.
- **The review loop is visible.** `/review` shows the 56-line queue and the
  30-line sign-off gate; no native-quality average is shown before sign-off.
- **CI is read-only.** Azure deployment is a manual operator action.

---

## Colour and style notes for Eraser

- Background: `#0a0a0f` (matches the UI dark base).
- Group borders: violet for Pipeline/AI, cyan for Backend, emerald for
  Frontend, amber for Data, slate for Delivery/Observability.
- Arrow style: **curved**, weight **1.5px**, colour `#52525b`.
- Keep the failure paths visually secondary. Do not draw the audio branch as
  part of the verified caption path.
- Export at **2× PNG**, 1920 px wide minimum, for the pitch deck.
- For the README, use the Mermaid diagram instead; GitHub renders Mermaid
  natively.

---

## Which to use where

| Context | Format |
|---|---|
| GitHub README | Mermaid (renders inline, no image needed) |
| Full engineering review | Mermaid in [`architecture.md`](architecture.md) |
| Full Eraser schema | [`architecture-eraser-schema.md`](architecture-eraser-schema.md) |
| Pitch deck slide | Eraser.io PNG export (2× dark) |
| `/about` page in the UI | Link to the README or this diagram |
| Innovation Studio submission | Eraser.io PNG attached to the project description |
