# Msimulizi — Eraser.io Architecture Schema

This document is the complete, current input for generating the Msimulizi
architecture diagram in [Eraser.io](https://app.eraser.io). It covers the
browser, both Container Apps, event sources, the six-stage pipeline, the
caption-first audio branch, all six Cosmos containers, Blob audio, Key Vault,
observability, the monthly budget, and the read-only CI/manual-delivery path.

The canonical engineering view is the Mermaid diagram set in
[`architecture.md`](architecture.md). This file is the Eraser-specific schema and
generation contract. The older compact pitch-deck block in
[`architecture-eraser-spec.md`](architecture-eraser-spec.md) is kept for
existing slide links; use this schema for the full diagram.

> **Status:** 27 October 2026. Backend is one replica; native review is 0/56;
> no native-quality average is publishable yet. CI never deploys to Azure.

---

## 1. How to use it

1. Open Eraser.io → **New Diagram** → **Cloud Architecture**.
2. Paste the `Eraser.io diagram-as-code` block from section 5 into the
   diagram-as-code editor.
3. Use **dark** theme, **left-to-right** layout, and export a **2× PNG** at
   1920 px wide or larger.
4. Do not add a deployed CI arrow, a multi-replica backend, a native-quality
   score, or a real club/player mark. Those are not in the schema.

The current rendered export is [`architecture-overview.png`](architecture-overview.png)
(3786 × 2490). It is linked from [`README.md`](../README.md) and
[`architecture.md`](architecture.md).

The schema is intentionally explicit: if a component or edge is not listed
here, do not infer it from a generic Azure reference architecture.

---

## 2. Diagram contract

```yaml
diagram:
  title: Msimulizi — AI Match Intelligence
  audience: hackathon judges and engineering review
  direction: left-to-right
  theme: dark
  canvas: 2400x1500
  export: png-2x
  primary_path: caption
  secondary_path: audio
  annotations:
    - one backend replica
    - caption first, audio second
    - MCP bearer auth
    - CI read-only for Azure
    - native review gate: 30 signed-off lines
```

---

## 3. Group schema

| Group ID | Eraser label | Purpose | Colour token |
|---|---|---|---|
| `Actors` | Actors and clients | People and tool clients entering the system | slate |
| `Frontend` | Next.js frontend Container App | Browser UI, runtime config route, reviewer dashboard | emerald |
| `Sources` | Event sources | Synthetic generator, file replay, Event Hubs-shaped adapter | slate |
| `Backend` | FastAPI backend Container App — min 1 / max 1 replica | API, WebSocket, MCP, session manager, audio service, in-memory state | cyan |
| `Pipeline` | Commentary pipeline | Deterministic stages, model stages, verification, rendering, fallbacks | violet |
| `AIServices` | Azure AI services | Foundry, Speech, Content Safety | violet |
| `CosmosDB` | Cosmos DB — database msimulizi | Six durable containers and their partition keys | amber |
| `Storage` | Storage and secrets | Audio blobs and Key Vault secrets | amber |
| `Observability` | Observability and cost | Application Insights, Log Analytics, monthly budget | slate |
| `Delivery` | Delivery | Read-only CI, ACR, Container Apps revisions | slate |

---

## 4. Node schema

| Node ID | Group | Eraser icon | Represents | Canonical source |
|---|---|---|---|---|
| `Viewer` | `Actors` | `user` | Viewer or judge using the public demo | `frontend/src/app/page.tsx` |
| `Reviewer` | `Actors` | `check-square` | Named Swahili reviewer using `/review` | `docs/native-speaker-review.md` |
| `Operator` | `Actors` | `settings` | Human running manual deployments and checking alerts | `README.md` |
| `Developer` | `Actors` | `code` | Contributor running tests and checks | `.github/workflows/ci.yml` |
| `ToolClient` | `Actors` | `terminal` | Authenticated MCP client | `mcp_server/server.py` |
| `ViewerUI` | `Frontend` | `layout` | `/` and `/about` viewer surfaces | `frontend/src/app/page.tsx` |
| `RuntimeConfig` | `Frontend` | `settings` | `/api/config` runtime backend and WS URLs | `frontend/src/app/api/config/route.ts` |
| `ReviewUI` | `Frontend` | `bar-chart-2` | `/review` reviewer dashboard | `frontend/src/app/review/page.tsx` |
| `Generator` | `Sources` | `cpu` | Deterministic synthetic match generator | `generator/generate.py` |
| `FileReplay` | `Sources` | `file` | File replay adapter with checkpointing | `adapter/file_replay.py` |
| `EventHubsShape` | `Sources` | `azure-event-hubs` | Event Hubs-shaped local/checkpoint adapter | `adapter/eventhubs.py` |
| `Adapter` | `Backend` | `shuffle` | Adapter factory selected by `EVENT_SOURCE` | `adapter/factory.py` |
| `REST` | `Backend` | `server` | `/v1` cards, state, audit, corrections, review, and `/health` | `api/routes.py`, `api/main.py` |
| `WS` | `Backend` | `radio` | `/ws` card, clock, event, audio, and score pushes | `api/websocket.py` |
| `MCP` | `Backend` | `terminal` | FastMCP `/mcp/` with bearer authentication | `mcp_server/server.py` |
| `Session` | `Backend` | `users` | SessionManager and per-session pipeline task | `api/main.py`, `api/pipeline_runner.py` |
| `Audio` | `Backend` | `volume-2` | Memoized, single-flight, breaker-protected audio service | `renderer/audio/service.py` |
| `InMemory` | `Backend` | `database` | PubSub latest state, narration cache, corrections, session state | `shared/pubsub.py`, `shared/cosmos.py` |
| `Interpreter` | `Pipeline` | `activity` | Match state, clock, event dots, momentum and stats | `pipeline/interpreter.py` |
| `Moment` | `Pipeline` | `zap` | Trigger tags and priority selection | `pipeline/moment.py` |
| `Personaliser` | `Pipeline` | `user` | Profile key, language, mode, club perspective, cache lookup | `pipeline/personaliser.py` |
| `Explainer` | `Pipeline` | `book-open` | Structured reason, evidence, numeric grounding | `pipeline/explainer.py` |
| `Narrator` | `Pipeline` | `message-square` | Localized card and Swahili English gloss | `pipeline/narrator.py` |
| `Verifier` | `Pipeline` | `check-circle` | Number, claim, evidence, and safety verification | `pipeline/verifier.py` |
| `Renderer` | `Pipeline` | `layers` | Card contract, persistence handoff, fallback cards | `renderer/renderer.py` |
| `Bundle` | `Pipeline` | `archive` | Pre-generated bundle card fallback | `bundle/`, `api/pipeline_runner.py` |
| `Template` | `Pipeline` | `file-text` | Deterministic fallback line | `renderer/fallback.py` |
| `Foundry` | `AIServices` | `azure-openai` | `gpt-5.4` / `gpt-5.4-mini` deployments | `config/foundry_models.yaml` |
| `Speech` | `AIServices` | `azure-cognitive-services` | Swahili, English, and French neural TTS | `renderer/audio/config.py` |
| `Safety` | `AIServices` | `shield` | Azure AI Content Safety | `shared/content_safety.py` |
| `Snapshots` | `CosmosDB` | `file` | `match_state_snapshots`, PK `/match_id` | `shared/cosmos.py` |
| `Moments` | `CosmosDB` | `zap` | `key_moments`, PK `/match_id` | `shared/cosmos.py` |
| `NarrationCache` | `CosmosDB` | `message-square` | `narration_cache`, PK `/profile_key` | `shared/cosmos.py` |
| `Cards` | `CosmosDB` | `layers` | `overlay_cards`, PK `/match_id`, 86,400 s TTL | `shared/cosmos.py` |
| `Audit` | `CosmosDB` | `shield` | `audit_log`, PK `/match_id`, create-only app path | `shared/cosmos.py` |
| `Corrections` | `CosmosDB` | `check-square` | `corrections`, PK `/match_id`, viewer and native review | `shared/cosmos.py` |
| `Blob` | `Storage` | `azure-blob-storage` | Public-read audio container | `renderer/audio/stores.py` |
| `KeyVault` | `Storage` | `azure-key-vault` | MCP and reviewer keys via managed identity | `infra/main.bicep` |
| `AppInsights` | `Observability` | `azure-monitor` | OpenTelemetry metrics and workspace telemetry | `shared/observability.py` |
| `LogAnalytics` | `Observability` | `file-text` | Container Apps logs, 30-day retention | `infra/main.bicep` |
| `Budget` | `Observability` | `dollar-sign` | Monthly consumption budget and alerts | `infra/budget.bicep` |
| `CI` | `Delivery` | `github` | Hygiene, Ruff, pytest, Vitest, generator validation; no Azure login | `.github/workflows/ci.yml` |
| `ACR` | `Delivery` | `azure-container-registry` | Image registry, admin user disabled | `infra/main.bicep` |
| `Revision` | `Delivery` | `box` | Container Apps revision receiving 100% traffic | `azure.yaml` |

---

## 5. Critical edge contract

| Flow | Edges | Why it matters |
|---|---|---|
| Viewer entry | `Viewer → ViewerUI`, `ViewerUI → RuntimeConfig`, `ViewerUI → REST`, `ViewerUI ↔ WS` | The browser reads runtime URLs, then talks to the backend directly |
| Reviewer entry | `Reviewer → ReviewUI`, `ReviewUI → REST` | Reviewer key gates `/v1/review` and `/v1/review/swahili` |
| MCP entry | `ToolClient → MCP` | Bearer token required; unauthenticated access returns 401 |
| Event source | `Generator/FileReplay/EventHubsShape → Adapter → Interpreter` | All sources use one pipeline contract |
| Caption path | `Interpreter → Moment → Personaliser → Explainer → Narrator → Verifier → Renderer → WS` | Caption is the primary surface |
| Cache hit | `Personaliser → Renderer` | Approved bundle/cache line bypasses live models |
| Verification retry | `Verifier → Narrator` | One retry before fallback |
| Quota fallback | `Narrator → Bundle → Renderer` | A model quota failure still produces a caption |
| Failure fallback | `Verifier → Template → Renderer` | Rejected or timed-out verification still produces a caption |
| Audio path | `Renderer → Audio`, `Audio → Speech`, `Audio → Blob`, `Audio → WS` | Audio runs after the caption and never rewrites it |
| Spoken rewrite | `Audio → Foundry` | Optional grounded rewrite; invalid output synthesizes the caption |
| AI grounding | `Explainer/Narrator/Verifier → Foundry`, `Verifier → Safety` | Models generate; verifier and safety gate them |
| State persistence | `Interpreter → Snapshots`, `Moment → Moments`, `Narrator → NarrationCache` | Durable match and cache state |
| Card persistence | `Renderer → Cards`, `Renderer → Audit` | Cards and verdict/audit trail are persisted |
| Review persistence | `REST → Corrections` | Viewer feedback and native review share the container |
| MCP reads | `MCP → Snapshots/Moments/InMemory` | Live state first, durable snapshot second |
| Secrets | `KeyVault → REST`, `KeyVault → MCP` | Managed identity at startup; no committed secrets |
| Metrics | `Renderer → AppInsights`, `Audio → AppInsights` | OTel metric path |
| Logs | `REST → LogAnalytics`, `Audio → LogAnalytics` | Container Apps log path |
| Cost | `Budget → Operator` | Budget notifications are the codified alert path |
| Delivery | `Developer → CI`, `Operator → ACR`, `Operator → Revision`, `ACR → Revision`, `Revision → ViewerUI/REST` | CI is read-only; deployment is manual |

**Do not draw:** `CI → ACR`, `CI → Revision`, `CI → Azure`, a second backend
replica, a shared WebSocket backplane, a vector database, or a native-quality
score. Those are not current.

---

## 6. Eraser.io diagram-as-code

```
// Msimulizi — AI Match Intelligence
// Full Eraser schema, synced with docs/architecture.md
// Theme: dark  |  Layout: left-to-right
// Last updated: 27 October 2026
//
// Caption path is primary. Audio path is secondary and fail-open.
// Backend is intentionally one replica until a shared backplane exists.

// ── Colour tokens ──────────────────────────────────────────────
// violet  = #7c3aed   (pipeline / AI)
// cyan    = #06b6d4   (API / backend)
// emerald = #10b981   (frontend / UI)
// slate   = #334155   (actors, delivery, observability)
// amber   = #f59e0b   (storage / data)

// ── Actors and clients ─────────────────────────────────────────
group Actors [Actors and clients] {
  color: slate
  Viewer [icon: user, label: "Viewer / judge", color: slate]
  Reviewer [icon: check-square, label: "Swahili reviewer", color: slate]
  Operator [icon: settings, label: "Operator", color: slate]
  Developer [icon: code, label: "Developer", color: slate]
  ToolClient [icon: terminal, label: "MCP client\nbearer token", color: slate]
}

// ── Frontend ───────────────────────────────────────────────────
group Frontend [Next.js frontend Container App] {
  color: emerald
  ViewerUI [icon: layout, label: "Viewer\n/ , /about", color: emerald]
  RuntimeConfig [icon: settings, label: "/api/config\nruntime backend + WS URLs", color: emerald]
  ReviewUI [icon: bar-chart-2, label: "/review\nreviewer dashboard", color: emerald]
}

// ── Event sources ──────────────────────────────────────────────
group Sources [Event sources] {
  color: slate
  Generator [icon: cpu, label: "Synthetic generator\nstoryline + seed", color: slate]
  FileReplay [icon: file, label: "File replay\nJSONL + checkpoint", color: slate]
  EventHubsShape [icon: azure-event-hubs, label: "Event Hubs-shaped\ncheckpoint adapter", color: slate]
}

// ── Backend ────────────────────────────────────────────────────
group Backend [FastAPI backend Container App — min 1 / max 1 replica] {
  color: cyan
  Adapter [icon: shuffle, label: "Adapter factory\nEVENT_SOURCE", color: cyan]
  REST [icon: server, label: "REST /v1\n+ /health", color: cyan]
  WS [icon: radio, label: "WebSocket /ws\nheartbeat", color: cyan]
  MCP [icon: terminal, label: "FastMCP /mcp/\nbearer auth · 401 without key", color: cyan]
  Session [icon: users, label: "SessionManager\n+ pipeline task", color: cyan]
  Audio [icon: volume-2, label: "AudioService\nmemo + single-flight + breaker", color: cyan]
  InMemory [icon: database, label: "In-memory state\nPubSub + caches + corrections", color: cyan]
}

// ── Commentary pipeline ────────────────────────────────────────
group Pipeline [Commentary pipeline] {
  color: violet
  Interpreter [icon: activity, label: "Interpreter\nstate + clock + event dots", color: violet]
  Moment [icon: zap, label: "Moment\ntags + priority", color: violet]
  Personaliser [icon: user, label: "Personaliser\nprofile key + cache", color: violet]
  Explainer [icon: book-open, label: "Explainer\nreason + evidence", color: violet]
  Narrator [icon: message-square, label: "Narrator\ncard + English gloss", color: violet]
  Verifier [icon: check-circle, label: "Verifier\nnumbers + safety", color: violet]
  Renderer [icon: layers, label: "Renderer\ncard + fallback", color: violet]
  Bundle [icon: archive, label: "Bundle fallback\npre-generated cards", color: violet]
  Template [icon: file-text, label: "Template fallback\nline", color: violet]
}

// ── Azure AI services ──────────────────────────────────────────
group AIServices [Azure AI services] {
  color: violet
  Foundry [icon: azure-openai, label: "Microsoft Foundry\ngpt-5.4 / gpt-5.4-mini\n4 deployments", color: violet]
  Speech [icon: azure-cognitive-services, label: "Azure AI Speech\nsw-KE · sw-TZ · en · fr", color: violet]
  Safety [icon: shield, label: "Content Safety", color: violet]
}

// ── Cosmos DB ──────────────────────────────────────────────────
group CosmosDB [Cosmos DB — database msimulizi] {
  color: amber
  Snapshots [icon: file, label: "match_state_snapshots\nPK /match_id", color: amber]
  Moments [icon: zap, label: "key_moments\nPK /match_id", color: amber]
  NarrationCache [icon: message-square, label: "narration_cache\nPK /profile_key", color: amber]
  Cards [icon: layers, label: "overlay_cards\nPK /match_id · 24h TTL", color: amber]
  Audit [icon: shield, label: "audit_log\nPK /match_id", color: amber]
  Corrections [icon: check-square, label: "corrections\nviewer + native review", color: amber]
}

// ── Storage and secrets ────────────────────────────────────────
group Storage [Storage and secrets] {
  color: amber
  Blob [icon: azure-blob-storage, label: "Blob Storage\naudio container\npublic blob read", color: amber]
  KeyVault [icon: azure-key-vault, label: "Key Vault\nMCP + reviewer keys", color: amber]
}

// ── Observability and cost ─────────────────────────────────────
group Observability [Observability and cost] {
  color: slate
  AppInsights [icon: azure-monitor, label: "Application Insights\nOTel metrics", color: slate]
  LogAnalytics [icon: file-text, label: "Log Analytics\n30-day logs", color: slate]
  Budget [icon: dollar-sign, label: "Monthly budget\n50 / 80 / 100 alerts", color: slate]
}

// ── Delivery ───────────────────────────────────────────────────
group Delivery [Delivery] {
  color: slate
  CI [icon: github, label: "GitHub Actions CI\nhygiene · Ruff · pytest · Vitest\nno Azure login", color: slate]
  ACR [icon: azure-container-registry, label: "ACR\nimages", color: slate]
  Revision [icon: box, label: "Container Apps\nrevision", color: slate]
}

// ── Actors and entry points ────────────────────────────────────
Viewer --> ViewerUI
Reviewer --> ReviewUI
ToolClient --> MCP
Developer --> CI

ViewerUI --> RuntimeConfig
ViewerUI --> REST
ViewerUI --> WS
ReviewUI --> REST

// ── Event sources and session ──────────────────────────────────
Generator --> Adapter
FileReplay --> Adapter
EventHubsShape --> Adapter
REST --> Session
Session --> Adapter
Session --> InMemory

// ── Caption path ───────────────────────────────────────────────
Adapter --> Interpreter
Interpreter --> Moment
Moment --> Personaliser
Personaliser --> Explainer
Explainer --> Narrator
Narrator --> Verifier
Verifier --> Renderer
Interpreter --> WS
Interpreter --> InMemory

// ── Cache and fallback paths ───────────────────────────────────
Personaliser --> Renderer
Verifier --> Narrator
Narrator --> Bundle
Verifier --> Template
Bundle --> Renderer
Template --> Renderer

// ── Caption delivery and persistence ───────────────────────────
Renderer --> WS
Renderer --> Cards
Renderer --> Audit
Renderer --> Audio
Renderer --> AppInsights
Interpreter --> Snapshots
Moment --> Moments
Narrator --> NarrationCache
REST --> Snapshots
REST --> Cards
REST --> Audit
REST --> Corrections
REST --> InMemory
MCP --> Snapshots
MCP --> Moments
MCP --> InMemory

// ── AI services ────────────────────────────────────────────────
Explainer --> Foundry
Narrator --> Foundry
Verifier --> Foundry
Verifier --> Safety
Audio --> Foundry

// ── Audio enhancement, after the caption ───────────────────────
Audio --> Speech
Audio --> Blob
Audio --> WS
Audio --> AppInsights

// ── Secrets, logs, and cost ────────────────────────────────────
KeyVault --> REST
KeyVault --> MCP
REST --> LogAnalytics
Audio --> LogAnalytics
AppInsights --> LogAnalytics
Budget --> Operator

// ── Manual delivery; CI has no Azure arrows ────────────────────
Operator --> ACR
Operator --> Revision
ACR --> Revision
Revision --> ViewerUI
Revision --> REST
```

---

## 7. Layout and visual contract

- **Direction:** left-to-right. Actors on the far left; frontend/backend in the
  centre; AI and data on the right; observability and delivery below or above.
- **Primary path:** make the caption path visually dominant. It is the line
  from `Adapter` through `Renderer` to `WS`.
- **Audio path:** draw it as a secondary branch from `Renderer` to `Audio` to
  `Speech`/`Blob` and back to `WS`. Never draw audio before the caption.
- **Fallbacks:** keep `Bundle` and `Template` visually subordinate. They are
  recovery paths, not the main narration path.
- **Replica label:** the backend group must say **min 1 / max 1 replica**.
- **CI:** show `Developer → CI`; do not draw `CI → ACR`, `CI → Revision`, or any
  CI-to-Azure edge.
- **MCP:** show `ToolClient → MCP` and label the bearer requirement.
- **Review:** show `/review` as a reviewer surface with its own REST calls.
- **Data:** show the six Cosmos containers with partition keys/TTL, Blob audio,
  and Key Vault secrets. Do not collapse them into a single "database" box.
- **No trademarks:** no real club crests, player images, league logos, or
  third-party marks.

---

## 8. Generation brief for Eraser AI

If you are using Eraser's AI generation rather than the DSL block, use this
brief:

> Create a dark, left-to-right Azure cloud architecture diagram for Msimulizi,
> a live football commentary system. Show a Next.js frontend Container App and
> a FastAPI backend Container App pinned to one replica. The browser connects
> directly to the backend REST and WebSocket ingress and reads runtime URLs from
> `/api/config`. Show the synthetic/file/Event-Hubs-shaped event sources, the
> six-stage commentary pipeline (Interpreter, Moment, Personaliser, Explainer,
> Narrator, Verifier), the Renderer, and the fallback paths. Make the caption
> path dominant. Draw audio as a secondary branch from Renderer through
> AudioService to Azure AI Speech, Blob Storage, and back to the WebSocket; show
> the optional Foundry spoken rewrite. Include Microsoft Foundry, Content
> Safety, all six Cosmos containers, Key Vault, Application Insights, Log
> Analytics, a monthly budget, and a read-only GitHub Actions CI. Show manual
> `azd deploy` through ACR to Container Apps revisions. Label the MCP endpoint
> with bearer authentication and the native review gate. Do not draw CI
> deploying to Azure, a second backend replica, or a native-quality score.

---

## 9. Coverage checklist

Use this before exporting:

- [ ] All four actors: viewer, reviewer, operator, developer.
- [ ] MCP client and bearer-authenticated `/mcp/`.
- [ ] Three event source shapes and the adapter factory.
- [ ] Six pipeline stages plus renderer.
- [ ] Cache-hit, quota, verifier-retry, and template fallbacks.
- [ ] Caption delivered before audio.
- [ ] Spoken rewrite from Foundry, Speech synthesis, Blob storage, `audio_update`.
- [ ] All six Cosmos containers with partition keys and card TTL.
- [ ] Key Vault secrets.
- [ ] Application Insights, Log Analytics, and budget alerts.
- [ ] One backend replica; frontend 1–3.
- [ ] CI read-only; manual ACR/revision deployment.
- [ ] Review queue 0/56 and the 30-line export gate represented in the caption
      or adjacent note.
- [ ] No secrets, real player images, or third-party club marks.
