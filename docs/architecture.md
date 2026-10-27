# Msimulizi — Architecture and Runtime Diagrams

This is the current component map for the demo as it runs on 27 October 2026.
It covers the Azure infrastructure, the backend pipeline, the Next.js viewer,
the data model, and the observability/review loop.

The diagrams are intentionally explicit about the demo's constraints:

- Synthetic data only; no real clubs, players, or third-party marks.
- The backend runs at **one replica** (`minReplicas: 1`, `maxReplicas: 1`)
  because active sessions, WebSockets, caches, and the pub/sub bus are
  process-local.
- Captions are the primary surface. Audio is rendered after the caption and is
  fail-open: a rewrite, TTS, or storage failure never removes the caption.
- The native-speaker review queue is real work, not a quality claim. The
  current queue is **0/56 signed off**, so no average is publishable.
- CI is read-only with respect to Azure. Deployments are explicit operator
  actions with `azd deploy backend` / `azd deploy frontend`.

For the vocabulary, see [`glossary.md`](glossary.md). For the demo sequence,
see [`demo-guide.md`](demo-guide.md). For the complete Eraser.io diagram schema,
see [`architecture-eraser-schema.md`](architecture-eraser-schema.md); the smaller
pitch-deck block is in [`architecture-eraser-spec.md`](architecture-eraser-spec.md).

---

## 1. System context

```mermaid
flowchart LR
    Viewer(["Viewer / judge"])
    Reviewer(["Swahili reviewer"])
    Operator(["Operator"])

    subgraph Azure["Azure resource group: rg-msimulizi-demo2"]
        FE["Next.js frontend<br/>Container App"]
        BE["FastAPI backend<br/>Container App<br/>min 1 / max 1 replica<br/>/v1, /ws, /mcp"]
        Foundry["Microsoft Foundry<br/>gpt-5.4 and gpt-5.4-mini"]
        Speech["Azure AI Speech<br/>Swahili, English, French"]
        Safety["Azure AI Content Safety"]
        Cosmos["Cosmos DB<br/>six containers"]
        Blob["Blob Storage<br/>audio container"]
        KV["Key Vault"]
        AI["Application Insights"]
        LAW["Log Analytics"]
        Budget["Consumption budget"]
    end

    Viewer -->|"HTTPS"| FE
    Viewer -->|"REST + WSS"| BE
    Reviewer -->|"HTTPS + reviewer key"| FE
    Reviewer -->|"review API"| BE
    Operator -->|"manual azd deploy"| FE
    Operator -->|"manual azd deploy"| BE
    Operator -->|"budget notifications"| Budget

    FE -.->|"BACKEND_URL / WS_URL"| BE
    BE -->|"structured output"| Foundry
    BE -->|"TTS"| Speech
    BE -->|"moderation"| Safety
    BE -->|"state, cards, audit, review"| Cosmos
    BE -->|"audio read / write"| Blob
    BE -->|"secrets via managed identity"| KV
    BE -->|"custom metrics"| AI
    AI -->|"workspace-based telemetry"| LAW
```

The public demo is available through **10 November 2026**. The frontend and
backend are separate Container Apps, but the browser talks to the backend
directly for REST and WebSocket traffic. The frontend's `/api/config` route
supplies the runtime backend and WebSocket URLs so one frontend image works
across environments.

---

## 2. Container and runtime view

```mermaid
flowchart TB
    subgraph Browser["Browser"]
        Pages["Next.js pages<br/>/ , /about , /review"]
        Config["/api/config<br/>runtime URLs"]
        Socket["useMatchSocket<br/>WS + heartbeat"]
        Clock["useSessionClock<br/>forward-only anchors"]
        Scheduler["Card scheduler<br/>priority + audio patch"]
        View["Clock, score, pitch, HUD,<br/>cards, audio, profile, replay"]
        Pages --> Config
        Pages --> Socket
        Socket --> Clock
        Socket --> Scheduler
        Clock --> View
        Scheduler --> View
    end

    subgraph ACA["Azure Container Apps environment"]
        subgraph FrontendApp["Frontend Container App"]
            NJS["Next.js server<br/>static UI + /api/config"]
        end
        subgraph BackendApp["Backend Container App"]
            API["FastAPI<br/>/health + /v1/*"]
            WS["WebSocket gateway<br/>/ws"]
            MCP["FastMCP<br/>/mcp/ with bearer auth"]
            SM["SessionManager<br/>and pipeline tasks"]
            PIPE["pipeline_runner<br/>one asyncio task per session"]
            AUD["AudioService<br/>memo, single-flight, breaker"]
            MEM["In-memory state<br/>PubSub, caches, corrections"]
        end
    end

    Foundry["Microsoft Foundry"]
    Speech["Azure AI Speech"]
    Safety["Azure AI Content Safety"]
    Cosmos["Cosmos DB"]
    Blob["Blob Storage"]
    KV["Key Vault"]
    AI["Application Insights"]
    LAW["Log Analytics"]

    NJS -->|"HTML / JS"| Pages
    Pages -->|"GET /api/config"| NJS
    Config -->|"backendUrl, wsUrl"| Pages
    Pages -->|"POST /v1/sessions<br/>review + corrections"| API
    Socket -->|"WSS /ws"| WS

    API --> SM
    SM --> PIPE
    PIPE --> MEM
    PIPE --> WS
    PIPE --> AUD
    PIPE --> Foundry
    PIPE --> Safety
    PIPE --> Cosmos
    AUD --> Speech
    AUD --> Blob
    AUD --> WS
    API --> Cosmos
    API --> MEM
    MCP --> MEM
    MCP --> Cosmos

    KV -.->|"secrets"| BackendApp
    PIPE -.->|"OTel metrics"| AI
    API -.->|"logs"| LAW
    NJS -.->|"logs"| LAW
    AI --> LAW
```

The frontend does not proxy match traffic. It serves the UI and runtime
configuration; the browser connects to the backend's public `/v1` and `/ws`
ingress. The MCP surface is mounted inside the backend process at `/mcp/`, so
it shares the same Cosmos repositories, pub/sub bus, and process lifecycle.

MCP authentication is required in production: the client sends a bearer token,
and an unauthenticated request to `/mcp/` returns `401`. The key is stored in
Key Vault and injected as a Container App secret; it is never committed.

### Why the backend is pinned to one replica

`SessionManager`, `WebSocketManager`, `PubSub`, narration caches, and the
in-flight audio map are in-memory. A second replica would not see the first
replica's sessions, WebSocket connections, or live state. The current
`minReplicas: 1` / `maxReplicas: 1` setting is therefore a correctness
constraint, not a cost optimum. Scaling wider requires a shared session and
WebSocket backplane first.

---

## 3. Backend pipeline and fallback paths

```mermaid
flowchart TB
    subgraph Sources["Event source adapters"]
        GEN["Synthetic generator<br/>storyline + seed"]
        FILE["File replay<br/>JSONL + checkpoint"]
        EH["Event Hubs-shaped adapter<br/>JSONL + checkpoint"]
    end

    ADP["Adapter factory<br/>EVENT_SOURCE"]
    INT["Interpreter<br/>match state + player stats"]
    CLOCK["Clock and event-dot broadcast<br/>plus state snapshot"]
    MOM["Moment<br/>trigger tags + priority"]
    PER["Personaliser<br/>profile key + cache lookup"]
    CACHE[("In-memory narration cache<br/>seeded from bundle")]
    EXPL["Explainer<br/>structured reason + evidence"]
    NAR["Narrator<br/>localized headline/body + gloss"]
    VER["Verifier<br/>numbers, claims, evidence, safety"]
    REN["Renderer<br/>OverlayCard contract + fallback cards"]
    WS["WebSocket gateway"]
    PERSIST["Cosmos background writes"]
    PUBSUB[("PubSub<br/>latest live state")]
    MCP["MCP tools<br/>state, moments, player stats"]
    BUNDLE["Bundle fallback<br/>pre-generated cards"]
    TMPL["Template fallback line"]
    AUD["Audio branch<br/>rewrite + TTS + Blob"]

    Foundry["Foundry<br/>explainer / narrator / verifier<br/>plus spoken-script adapter"]
    Safety["Content Safety"]
    Cosmos["Cosmos DB"]
    Blob["Blob audio"]
    Speech["Azure AI Speech"]

    GEN --> ADP
    FILE --> ADP
    EH --> ADP
    ADP --> INT
    INT --> CLOCK
    INT --> MOM
    INT --> PUBSUB
    PUBSUB --> MCP
    MOM --> PER
    PER -->|"cache miss"| EXPL
    PER -->|"cache hit"| REN
    CACHE --> PER
    EXPL --> NAR
    NAR --> VER
    VER -->|"pass"| REN
    VER -->|"one retry"| NAR
    VER -->|"fail / timeout"| TMPL
    TMPL --> REN
    NAR -->|"quota exceeded"| BUNDLE
    BUNDLE -->|"approved card broadcast"| WS
    REN -->|"caption first"| WS
    REN --> PERSIST
    REN --> AUD
    AUD -->|"audio_update later"| WS
    AUD --> Speech
    AUD --> Blob
    AUD --> Foundry

    EXPL --> Foundry
    NAR --> Foundry
    VER --> Foundry
    VER --> Safety
    PERSIST --> Cosmos
```

The runtime path is explicit in `api/pipeline_runner.py`; it is not an opaque
agent graph. `pipeline/orchestrator.py` exposes the Agent Framework-compatible
session/workflow facade, while the live driver owns the per-session event loop.
This keeps the stage order, failure branches, and timing visible and testable.

### Caption and audio ordering

The renderer broadcasts the approved caption first. The audio branch is a
separate asyncio task so a slow model or Speech call never delays the card.
The approved caption is never rewritten by the audio path.

```mermaid
flowchart LR
    CARD["Approved card<br/>caption already broadcast"] --> SCRIPT["SpokenScriptEnhancer<br/>Foundry mini, 8 s budget"]
    SCRIPT --> VALID{"Grounded rewrite<br/>passes validation?"}
    VALID -->|"yes"| REQ["AudioRequest<br/>spoken text + English gloss"]
    VALID -->|"no / timeout / quota"| VERB["AudioRequest<br/>caption verbatim"]
    REQ --> SVC["AudioService<br/>cache key: text, voice,<br/>emotion, intensity"]
    VERB --> SVC
    SVC --> MEMO{"Memo or store hit?"}
    MEMO -->|"yes"| UPDATE["audio_update"]
    MEMO -->|"no"| BUDGET{"Speech budget<br/>available?"}
    BUDGET -->|"no"| FAIL["audio_url = null<br/>caption remains"]
    BUDGET -->|"yes"| TTS["Azure AI Speech<br/>SSML + prosody"]
    TTS --> STORE["Blob audio container"]
    STORE --> UPDATE
    UPDATE --> WS["WebSocket"]
    FAIL --> WS
```

`AUDIO_SCRIPT_ENHANCE=true` enables the optional rewrite. Setting it to
`false` synthesizes the approved caption verbatim. A rewrite is exposed on
`audio_update` as `spoken_text` plus `spoken_gloss_en` only when it differs
from `source_text`; the card stays unchanged.

### Fallback summary

| Failure | Fallback | Caption still delivered? |
|---|---|---|
| Foundry timeout or 429 | Bundle card, then deterministic template line | Yes |
| Verifier rejection | One Narrator retry, then template fallback | Yes |
| Content Safety block | Fallback line or drop stat/spotlight card | Yes for key moments |
| Cosmos unavailable | In-memory stores plus write buffer | Yes |
| Speech timeout, budget, or breaker open | `audio_url: null` | Yes |
| Spoken rewrite invalid | Synthesize the approved caption verbatim | Yes |
| Out-of-order clock anchors | Frontend clamps to the newest forward anchor | Yes |

---

## 4. Frontend component and data flow

```mermaid
flowchart TB
    subgraph Routes["Next.js App Router"]
        Home["/ viewer"]
        About["/about"]
        Review["/review"]
        Config["/api/config"]
    end

    subgraph State["Viewer state"]
        Profile["ViewerProfile"]
        Match["MatchState"]
        Dots["EventDot array"]
        History["Card history"]
        Sched["SchedulerState<br/>current, pending, rank-1 queue"]
        Track["Audio track"]
        Clock["useSessionClock<br/>monotonic anchor"]
    end

    Socket["useMatchSocket"]
    API["Backend REST + WS"]

    subgraph UI["Viewer components"]
        Topbar["MatchClock + ScoreBar"]
        Pitch["PitchVisual<br/>heatmap, event dots, team_side"]
        HUD["MetricHUD<br/>possession, tilt, xG, tempo"]
        Feed["CardFeed<br/>current card + history"]
        Audio["CommentaryAudio"]
        Personal["PersonalisationPanel"]
        Replay["ReplayPanel<br/>storyline + speed"]
    end

    Home --> Socket
    Home --> Profile
    Home --> Sched
    Home -->|"POST /v1/sessions"| API
    API -->|"session_id, match_id"| Home
    Config -->|"backendUrl, wsUrl"| Home
    Socket -->|"WSS"| API
    Socket -->|"clock_update"| Clock
    Socket -->|"state_update, score_update, clock_update"| Match
    Socket -->|"event / event-dot packets"| Dots
    Socket -->|"card"| History
    Socket -->|"card, audio_update"| Sched
    Socket -->|"audio_update"| Track
    Socket -->|"profile_update, correction"| API
    Profile --> Personal
    Personal -->|"profile_update"| Socket
    Replay -->|"speed + storyline"| Home
    Feed -->|"thumb / edit"| Socket
    Clock --> Topbar
    Match --> Topbar
    Match --> HUD
    Dots --> Pitch
    Sched --> Feed
    History --> Feed
    Track --> Audio
    Home --> UI
    Review -->|"GET /v1/review<br/>POST /v1/review/swahili"| API
    About -->|"static disclosure"| Home
```

Key client-side rules:

- The clock is re-anchored to each authoritative card or event time and never
  moves backwards. `useSessionClock` takes the maximum of the incoming anchor
  and the visible clock while running.
- The scheduler shows one card at a time. Priority 1 cards are queued rather
  than dropped; lower-priority cards can be pre-empted or discarded once stale.
- `audio_update` patches both the card history and the scheduler copy, so the
  audio-only mode and the visual feed stay consistent.
- The reviewer page uses the reviewer key for `/v1/review` and
  `/v1/review/swahili`; it is a separate surface from the viewer.

---

## 5. Persistence and data model

```mermaid
flowchart TB
    subgraph Pipeline["Backend pipeline"]
        INT["Interpreter"]
        MOM["Moment"]
        NAR["Narrator / Verifier"]
        REN["Renderer"]
        APIR["REST API<br/>cards, state, audit, review"]
        MCP["MCP tools"]
    end

    subgraph Cosmos["Cosmos DB: database msimulizi, 400 RU/s"]
        SNAP[("match_state_snapshots<br/>PK /match_id<br/>no TTL")]
        MOMENTS[("key_moments<br/>PK /match_id<br/>no TTL")]
        NCACHE[("narration_cache<br/>PK /profile_key<br/>no TTL")]
        CARDS[("overlay_cards<br/>PK /match_id<br/>TTL 86,400 s")]
        AUDIT[("audit_log<br/>PK /match_id<br/>create-only app path")]
        CORR[("corrections<br/>PK /match_id<br/>viewer + native review")]
    end

    subgraph Runtime["Process-local state"]
        BUS[("PubSub<br/>latest match state")]
        SESS[("SessionManager<br/>WebSocket connections")]
        AMEM[("Audio memo + in-flight map")]
    end

    subgraph Storage["Blob Storage"]
        AUDIO[("audio container<br/>public blob read")]
    end

    INT -->|"snapshot"| SNAP
    INT -->|"live state"| BUS
    MOM -->|"moment"| MOMENTS
    NAR -->|"verified response"| NCACHE
    REN -->|"card"| CARDS
    REN -->|"audit entry"| AUDIT
    REN -->|"caption + rewrite"| AMEM
    AMEM -->|"MP3"| AUDIO
    APIR -->|"cards"| CARDS
    APIR -->|"state"| SNAP
    APIR -->|"audit"| AUDIT
    APIR -->|"viewer + native review"| CORR
    BUS --> MCP
    SNAP --> MCP
    MOMENTS --> MCP
    SESS -.->|"shares process"| BUS
```

The six containers are:

| Container | Partition key | TTL | Main writer / reader |
|---|---|---|---|
| `match_state_snapshots` | `/match_id` | none | Pipeline writes; MCP and REST read |
| `key_moments` | `/match_id` | none | Pipeline writes; MCP reads |
| `narration_cache` | `/profile_key` | none | Verifier-approved responses |
| `overlay_cards` | `/match_id` | 86,400 s | Renderer writes; REST reads |
| `audit_log` | `/match_id` | none | Renderer/verifier audit entries |
| `corrections` | `/match_id` | none | Viewer feedback and native review |

Cosmos is the durable store; the backend still keeps in-memory mirrors for
live state, bundle narration, reviewer corrections, and audio memoization. A
Cosmos write failure does not stop a caption: the repositories buffer writes,
and the in-memory mirror keeps the current session usable.

The **audio blob container** is public-read at the blob level so the browser
can play the MP3 directly. Writes use managed identity and the Storage Blob
Data Contributor role. There is no CDN or Front Door in the current stack.

---

## 6. Azure infrastructure topology

```mermaid
flowchart TB
    subgraph RG["Resource group: rg-msimulizi-demo2, eastus2"]
        subgraph Identity["Identity and secrets"]
            MI["User-assigned<br/>managed identity"]
            KV["Key Vault Standard<br/>RBAC + soft delete<br/>mcp-api-key, reviewer-api-key"]
            ACR["Container Registry Basic<br/>admin user disabled"]
        end

        subgraph Compute["Container Apps"]
            ENV["Container Apps environment<br/>Log Analytics destination"]
            BE["backend app<br/>0.5 CPU / 1 Gi<br/>min 1 / max 1"]
            FE["frontend app<br/>0.25 CPU / 0.5 Gi<br/>min 1 / max 3"]
        end

        subgraph AI["Azure AI services"]
            Foundry["Foundry S0<br/>4 model deployments"]
            Speech["Speech S0<br/>sw-KE, sw-TZ, en-US, fr-FR"]
            Safety["Content Safety S0"]
        end

        subgraph Data["Data"]
            Cosmos["Cosmos DB Standard<br/>Session consistency<br/>database msimulizi"]
            Storage["StorageV2 Standard_LRS<br/>public blob access<br/>audio container"]
        end

        subgraph Obs["Telemetry and cost"]
            AI2["Application Insights<br/>workspace-based"]
            LAW["Log Analytics<br/>30-day retention"]
            Budget["Consumption budget<br/>USD 100 monthly"]
        end
    end

    MI -->|"AcrPull"| ACR
    MI -->|"Key Vault Secrets User"| KV
    MI -->|"Cosmos DB Data Contributor"| Cosmos
    MI -->|"Storage Blob Data Contributor"| Storage
    MI -->|"Speech User"| Speech
    MI -->|"Cognitive Services User"| Safety
    MI -->|"Cognitive Services OpenAI User"| Foundry

    ACR -->|"image pull"| BE
    ACR -->|"image pull"| FE
    ENV --- BE
    ENV --- FE
    FE -.->|"BACKEND_URL / WS_URL"| BE
    BE -->|"OTel metrics"| AI2
    BE -->|"container logs"| LAW
    FE -->|"container logs"| LAW
    AI2 -->|"workspace"| LAW
    Budget -.->|"50 / 80 / 100 actual<br/>100 forecast alerts"| Operator["Operator email / Owner role"]
```

### Deployments and service choices

| Component | Current choice |
|---|---|
| Foundry | `gpt-5.4` for Swahili narration; `gpt-5.4-mini` for Explainer, Verifier, English/French narration, and spoken-script rewrites |
| Foundry deployments | `msimulizi-explainer`, `msimulizi-narrator-sw`, `msimulizi-narrator-en-fr`, `msimulizi-verifier` |
| Search / vector store | Not used; retrieval is deterministic event/state evidence |
| Speech | Azure AI Speech REST + SSML; Swahili voices `sw-KE-ZuriNeural`, `sw-TZ-RehemaNeural`, plus English and French |
| Event source | `EVENT_SOURCE=inprocess` by default; file replay and Event Hubs-shaped checkpoint adapters exist |
| Persistence | Cosmos DB, six containers; Blob Storage for audio |
| Secrets | Key Vault + user-assigned managed identity; live deployments use `KEY_MODE=preserve` |
| Hosting | Two Container Apps in one environment; backend one replica, frontend 1–3 |
| Budget | Separate `infra/budget.bicep` deployment; alerts at 50%, 80%, 100% actual and 100% forecast |

No virtual network, private endpoint, Front Door, CDN, Event Hubs namespace, or
App Insights alert rule is provisioned by `infra/main.bicep`. Those are
deliberate demo-scope choices, not claims of production hardening. The budget
is a guardrail, not a hard spend cap.

---

## 7. Observability and the review loop

```mermaid
flowchart LR
    subgraph Emit["Signal sources"]
        APILOG["FastAPI request / lifecycle logs"]
        PIPELOG["Pipeline logs<br/>[pipeline], [narrator],<br/>[verifier], [audio]"]
        AUDLOG["AudioService logs"]
        MET["MsimuliziFacade<br/>card_latency_ms, audio_latency_ms,<br/>verdict counts, fallback, quota"]
        AUDMET["Audio meter<br/>audio_render_ms,<br/>audio_render_total"]
    end

    subgraph Collect["Collection"]
        OTEL["OpenTelemetry<br/>Azure Monitor exporter"]
        STORE["In-process metric store"]
        LAW["Log Analytics<br/>Container Apps logs"]
    end

    subgraph Surface["Surfaces"]
        AI["Application Insights"]
        HEALTH["GET /health"]
        REVIEW["GET /v1/review<br/>reviewer key"]
        DASH["/review dashboard"]
        EVAL["Groundedness artifact<br/>evals/results/groundedness_latest.json"]
        HUMAN["Native review queue<br/>56 lines, 30-line export gate"]
    end

    APILOG --> LAW
    PIPELOG --> LAW
    AUDLOG --> LAW
    MET --> OTEL
    MET --> STORE
    AUDMET --> OTEL
    OTEL --> AI
    AI --> LAW
    STORE --> REVIEW
    EVAL --> REVIEW
    REVIEW --> DASH
    HUMAN --> DASH
```

### Instrumented metrics

| Metric | Type | Recorded by | Notes |
|---|---|---|---|
| `card_latency_ms` | histogram | `api/pipeline_runner.py` | Event receipt to card delivery; labels `language`, `card_type` |
| `audio_latency_ms` | histogram | `api/pipeline_runner.py` | Time around the audio task; audio is intentionally after the caption |
| `verdict_pass_count` | counter | Verifier | Emitted on a passing verdict |
| `verdict_fail_count` | counter | Verifier | Emitted on a failed verdict |
| `fallback_count` | counter | Verifier | Template fallback path |
| `quota_exceeded_count` | counter | Pipeline / audio | Model or Speech quota refusal |
| `audio_render_ms` | histogram | `renderer/audio/metrics.py` | Audio service render time by outcome, language, emotion |
| `audio_render_total` | counter | `renderer/audio/metrics.py` | Render outcomes, including cache hits and breaker opens |

`/v1/review` also exposes the in-process p50/p95 snapshot, verdict counts,
fallback/quota counts, the latest groundedness score, viewer corrections, and
the Swahili review queue. The in-process store is always written, so the
dashboard works without App Insights credentials.

### Current observability limits

- The review metrics are **process-local**. With one backend replica they are
  the process's current numbers; with more replicas each process would have its
  own snapshot. A shared metric backend would be needed before scaling.
- Custom OpenTelemetry **metrics** are instrumented. There is no custom
  distributed-tracing span instrumentation in the current code.
- Log Analytics receives Container Apps logs with 30-day retention. Application
  Insights is workspace-based.
- Budget notifications are the only codified alert path. No Application
  Insights alert rules are defined in Bicep.
- The groundedness artifact is a 50-entry heuristic pass at **1.0**. It is not a
  native-language quality score and must not be presented as one.
- The native review queue is **0/56**. The export gate refuses to publish an
  average before 30 distinct signed-off lines.

### Native review flow

```mermaid
sequenceDiagram
    actor R as Reviewer
    participant UI as /review page
    participant API as FastAPI
    participant DB as Cosmos corrections
    participant EXP as export_swahili_review.py

    R->>UI: enter reviewer key and name
    UI->>API: GET /v1/review with reviewer key
    API->>DB: list native reviews and viewer corrections
    DB-->>API: stored rows
    API-->>UI: metrics, 56-line queue, average null
    R->>UI: score fluency, idiom, faithfulness
    UI->>API: POST /v1/review/swahili
    API->>DB: create review entry
    API-->>UI: reviewed, requires_second_review if edited
    R->>EXP: export after 30 signed-off lines
    EXP-->>R: export, or refusal below threshold
```

A submitted line is marked reviewed, not automatically approved. Edited lines
require an independent second review before they can leave the export gate.

---

## 8. Live replay sequence

```mermaid
sequenceDiagram
    actor V as Viewer
    participant UI as Next.js viewer
    participant API as FastAPI /v1
    participant P as Pipeline task
    participant F as Foundry
    participant VF as Verifier + Safety
    participant DB as Cosmos DB
    participant WS as WebSocket
    participant A as AudioService
    participant S as Speech
    participant B as Blob

    V->>UI: choose storyline, language, speed
    UI->>API: POST /v1/sessions
    API->>P: spawn run_pipeline_session
    API-->>UI: session_id, match_id
    UI->>WS: connect /ws?session_id=...&match_id=...
    WS-->>UI: welcome

    loop each synthetic event
        P->>P: adapter -> Interpreter
        P->>WS: clock_update + event dot
        WS-->>UI: authoritative anchor + event dot
        P->>P: Moment -> Personaliser
        alt bundle or cache hit
            P->>P: approved card
        else live model path
            P->>F: Explainer structured output
            F-->>P: explanation + evidence
            P->>F: Narrator
            F-->>P: localized card + Swahili gloss
            P->>VF: verify claims, numbers, evidence, safety
            VF-->>P: pass, retry once, or fallback
        end
        P->>WS: card
        WS-->>UI: caption rendered and scheduled
        P->>DB: snapshot, moment, card, audit
        opt audio enabled
            P->>F: optional spoken rewrite, 8 s budget
            F-->>P: spoken text + gloss, or rejection
            P->>A: synthesize rewrite or caption
            A->>B: cache lookup
            A->>S: SSML + emotion/prosody
            S-->>A: MP3
            A->>B: store audio
            A->>WS: audio_update
            WS-->>UI: audio URL, optional spoken metadata
        end
    end

    Note over P,UI: The caption is authoritative. Audio never changes it.
```

If the audio rewrite is rejected, missing, or slow, the approved caption is
synthesized instead. If Speech is unavailable or over budget, the card remains
visible with `audio_url: null`.

---

## 9. Build, CI, and deployment

```mermaid
flowchart LR
    DEV["Developer"] -->|"git push"| CI["GitHub Actions CI<br/>hygiene, Ruff, pytest,<br/>Vitest, generator validation"]
    CI -->|"read-only checks"| MAIN["main branch"]
    MAIN --> OPS["Operator"]
    OPS -->|"azd deploy backend"| ACR["ACR build / push"]
    OPS -->|"azd deploy frontend"| ACR
    ACR --> REV["Container Apps revision<br/>100% traffic"]
    REV --> SMOKE["/health, /review,<br/>WebSocket + audio smoke"]
    BUDGET["infra/budget.bicep<br/>separate deployment"] --> ALERTS["50 / 80 / 100 actual<br/>100 forecast"]
    CI -.->|"no Azure login<br/>no provision<br/>no deploy"| OPS
```

CI does **not** create or modify Azure resources. It runs repository hygiene,
Ruff, backend tests, frontend tests, and generator validation. Deployment is an
explicit operator action: `azd deploy backend` or `azd deploy frontend`, then a
revision check and smoke test.

---

## 10. Current constraints and follow-ups

| Area | Current constraint | Follow-up |
|---|---|---|
| Backend scale | One replica because sessions and WebSockets are process-local | Add a shared session/WebSocket backplane before increasing replica count |
| Observability | `/v1/review` reads an in-process metric snapshot | Export/query a shared metric store if replicas increase |
| Tracing | Custom OTel metrics; no custom span instrumentation | Add request/event spans if deeper latency analysis is needed |
| Alerting | Budget alerts are codified | Add Application Insights alert rules for errors, latency, and dependency failures |
| Audit RBAC | `audit_log` is written through a create-only repository path; the Bicep custom role definition is not bound to the app identity | Decide whether to split identities/roles or document Data Contributor as the live scope |
| Network | Public Container Apps ingress; no VNet/private endpoints | Add private networking if the demo becomes a production service |
| Audio delivery | Public-read Blob container | Add CDN/Front Door and private origin if needed |
| Domain / CORS | Generated `*.azurecontainerapps.io` hostnames | Update custom domain and exact CORS origins before any public rebrand |
| Native review | 0/56 signed off; no published average | Complete the human review and export gate |
| Load testing | Not yet run for WebSockets, Speech, Foundry, Cosmos, or Blob egress | Load-test before increasing traffic or replicas |
| Event Hubs | Adapter shape exists; no Event Hubs namespace is provisioned | Provision and authenticate a live namespace if needed |

---

## 11. Source map

| Area | Files |
|---|---|
| App assembly, routes, WebSocket, pipeline driver | `api/main.py`, `api/routes.py`, `api/websocket.py`, `api/pipeline_runner.py` |
| Pipeline stages | `pipeline/interpreter.py`, `pipeline/moment.py`, `pipeline/personaliser.py`, `pipeline/explainer.py`, `pipeline/narrator.py`, `pipeline/verifier.py`, `pipeline/orchestrator.py` |
| Cards, fallback, audio | `renderer/renderer.py`, `renderer/fallback.py`, `renderer/audio/` |
| Shared services | `shared/cosmos.py`, `shared/foundry_client.py`, `shared/content_safety.py`, `shared/pubsub.py`, `shared/observability.py`, `shared/budget.py` |
| MCP | `mcp_server/server.py` |
| Event sources and generator | `adapter/`, `generator/` |
| Frontend | `frontend/src/app/`, `frontend/src/components/`, `frontend/src/hooks/`, `frontend/src/lib/` |
| Infrastructure | `infra/main.bicep`, `infra/budget.bicep`, `azure.yaml`, `Dockerfile.backend`, `frontend/Dockerfile` |
| CI and checks | `.github/workflows/ci.yml`, `scripts/check_repo_hygiene.py`, `scripts/run_groundedness_eval.py` |
| Review workflow | `docs/native-speaker-review.md`, `scripts/export_swahili_review.py`, `/review` |
