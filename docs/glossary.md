# Msimulizi — Project Glossary and How-To Index

This is the working vocabulary for the repository. It is written for someone
who needs to run the demo, review a card, change a storyline, or explain the
architecture without reading every module first.

For the submission plan, see [`demo-guide.md`](demo-guide.md). For the component
and runtime diagrams, see [`architecture.md`](architecture.md); for the
rendered overview, see
[`architecture-overview.png`](architecture-overview.png); for the Eraser.io
schema, see
[`architecture-eraser-schema.md`](architecture-eraser-schema.md). For the human
review protocol, see [`native-speaker-review.md`](native-speaker-review.md).
For the product scope, see [`msimulizi-project-brief.md`](msimulizi-project-brief.md).

> **Status snapshot — 27 October 2026**
>
> - Public demo: free through **10 November 2026**.
> - Backend: one active revision, **one replica**, scale-to-zero disabled.
> - Native-speaker queue: **0/56**; no average published.
> - Groundedness artifact: **1.0** on the shipped 50-entry heuristic eval.
> - CI: tests and checks only; it does **not** deploy or modify Azure.
> - No real clubs, players, third-party trademarks, or secrets are committed.

---

## 1. Product vocabulary

| Term | Meaning |
|---|---|
| **Msimulizi** | Swahili for “the narrator”. The product name. |
| **Match intelligence** | The combination of live state, key-moment selection, explanation, narration, and visual overlay. |
| **Synthetic match** | A deterministic match generated from a storyline YAML and a seed. Clubs and players are fictional. |
| **Storyline** | A seeded match shape such as `comeback_from_two_down`, `red_card_shift`, `late_equaliser`, or `dominant_side_loses`. |
| **Event** | One synthetic action: pass, shot, goal, card, period start, metadata. |
| **Key moment** | An event or short event cluster selected for a card: goal, big chance, red card, momentum swing, stat, recap. |
| **Overlay card** | The JSON object rendered in the viewer: headline, body, gloss, clock, evidence, card type, optional audio URL. |
| **Caption** | The card text shown on screen. Captions are the primary surface. |
| **English gloss** | The English translation shown with a Swahili card. Every Swahili card carries one. |
| **Perspective** | The viewer’s club focus: `home`, `away`, or `neutral`. It changes emphasis and emotion, not the underlying facts. |
| **Mode** | `casual` (short, fan-facing) or `analyst` (more context, metrics, and pitch detail). |
| **Audio-only mode** | A viewer mode that hides the visual feed and plays the commentary player. |
| **Correction** | A viewer-submitted suggestion on a card, stored for review. A correction is not automatically an approval. |
| **Review queue** | The 56 Swahili caption lines that a fluent reviewer scores in `/review`. |
| **Sign-off** | A named reviewer’s completed review of a line. A score is not publishable until the queue crosses the 30-line threshold. |

---

## 2. Pipeline vocabulary

The runtime path is:

```text
Generator → Adapter → Interpreter → Moment → Personaliser
          → Explainer → Narrator → Verifier → Renderer
          → WebSocket → Viewer
```

| Stage / term | Meaning |
|---|---|
| **Generator** | `generator/generate.py` and `generator/storylines/*.yaml`. Produces deterministic synthetic events. |
| **Adapter** | `adapter/` reads events and replays them at a speed multiplier. `FileReplayAdapter` is the replay path; `EventHubs` is the streaming shape. |
| **Interpreter** | Updates rolling match state: score, possession, xG, field tilt, momentum, tempo, pressure. |
| **Moment Agent** | Selects key moments and assigns priority/trigger tags. |
| **Personaliser** | Builds the narration request for language, mode, club perspective, player focus, and metric focus. |
| **Explainer** | Produces the structured explanation, evidence references, and card shape. |
| **Narrator** | Writes the localized headline/body and, for Swahili, the English gloss. |
| **Verifier** | Checks grounding, numbers, evidence, safety, and card contract before rendering. |
| **Renderer** | Builds the `OverlayCard`, sanitizes text, assigns IDs, and persists the card. |
| **Bundle** | A pre-generated package of audited cards and narrations used as a fallback when a live model call fails or quota is tight. |
| **Fallback** | The deterministic template path. It keeps the match moving when Foundry or a verifier call fails. |
| **Groundedness** | Whether a claim is supported by the event, state, or evidence. The heuristic eval is separate from native-language quality. |
| **Session** | One viewer replay: session ID, match ID, storyline, seed, speed, language, mode. |
| **Replay speed** | Match-time multiplier. `1×` is real-time; `30×` reaches match minute 12 in about 24 seconds. |
| **Clock re-anchor** | The frontend moves to the newest authoritative event/card time and never moves backwards. |
| **`team_side`** | Server-resolved `home`/`away` on an event dot. The raw team name may differ from the display label; the side is the stable mapping. |

---

## 3. Match and analyst vocabulary

| Term | Meaning |
|---|---|
| **xG** | Expected goals: a synthetic shot-quality estimate in the event stream. |
| **Possession** | Share of completed passes/possession events, shown as a percentage. |
| **Field tilt** | Territorial share based on where a team’s events occur. |
| **Momentum** | A rolling 0–100 style signal derived from recent event pressure. |
| **Tempo** | Events per minute in the recent window. |
| **Pressure rate** | Recent high-pressure events per minute. |
| **Event dot** | A point on the pitch visual for a recent event. |
| **Heatmap** | A composited visualization of event density over the drawn pitch. |
| **Team stats table** | The analyst table derived from event dots, mapped by `team_side` to the displayed home/away teams. |
| **Laplace smoothing** | The small prior used for possession/field-tilt percentages so an early match does not show a misleading 100%/0%. |
| **Score state** | `home_lead`, `away_lead`, or `level` at the moment of a card. Used by the audio rewrite to choose a grounded consequence. |
| **Match clock** | Authoritative `minute`/`second`/`match_seconds`. The viewer clock must be monotonic. |
| **Full time** | The terminal clock state at 90:00; the replay is finished. |

---

## 4. Audio vocabulary

| Term | Meaning |
|---|---|
| **TTS** | Text-to-speech. Production uses Azure AI Speech. |
| **SSML** | Speech Synthesis Markup Language. Built in `renderer/audio/ssml.py`. |
| **Prosody** | Rate, pitch, and volume shaping. Bounded so the voice does not sound theatrical. |
| **Emotion** | One of `neutral`, `anticipation`, `excitement`, `shock`, `relief`, `disappointment`, `tension`. |
| **Intensity** | 0–1 strength of the selected emotion. |
| **Perspective-aware emotion** | The same event can sound different for a home, away, or neutral viewer. The facts do not change. |
| **Sentence breath** | A short (~110 ms) pause between sentences for broadcast cadence. |
| **`StyleList`** | Azure voice style support. The Swahili voices exposed by this deployment have no `StyleList`, so expression comes from prosody and event mapping, not `express-as`. |
| **Voice** | Azure voice ID, for example `sw-KE-ZuriNeural`, `sw-KE-RafikiNeural`, `sw-TZ-RehemaNeural`, `sw-TZ-DaudiNeural`. |
| **Speech text** | The normalized text sent to TTS after punctuation/score cleanup. |
| **Spoken script** | The optional audio-only rewrite produced by Foundry from the approved caption. It is not the caption and is never rendered as the card. |
| **Spoken gloss** | The English gloss returned with a Swahili spoken script. It is carried in the audio update for audit. |
| **`AUDIO_SCRIPT_ENHANCE`** | Environment flag. Default `true`; set `false` to synthesize the approved caption verbatim. |
| **Audio request** | `AudioRequest`: narration ID, text, language, emotion, intensity, voice, minute, priority, source text, gloss. |
| **Audio result** | `AudioResult`: success, audio path, duration, error. |
| **Audio update** | The WebSocket message that patches an existing card with `audio_url` (and, when a rewrite is used, `spoken_text`, `source_text`, and `spoken_gloss_en`). |
| **Audio cache** | Content-addressed storage keyed by prepared text, voice, emotion, intensity, and related settings. |
| **Blob audio** | Audio files stored in Azure Blob Storage in production; local filesystem in offline development. |
| **`readyState=4`** | Browser audio element state meaning enough data is buffered to play. Used in manual smoke tests. |

### How the audio rewrite works

1. The caption is generated, verified, rendered, and broadcast first.
2. If `AUDIO_SCRIPT_ENHANCE` is enabled, `renderer/audio/script.py` sends the
   approved caption plus score state and event type to a Foundry structured
   output call.
3. The model returns `spoken_text` and `gloss_en`.
4. A validator rejects empty output, new numbers, verbatim captions, missing
   Swahili glosses, over-long output, meta-commentary, and malformed sentences.
5. On success, the spoken text is synthesized. On any failure, the approved
   caption is synthesized verbatim.
6. The card caption never changes.

The rewrite is a separate quality surface. The 56-line native review queue
covers caption cards; it does not separately score every audio rewrite.

---

## 5. Azure and infrastructure vocabulary

| Term | Meaning |
|---|---|
| **Azure AI Foundry** | The model endpoint. Production uses the unversioned `/openai/v1/` API. |
| **Deployment** | A named model deployment in `config/foundry_models.yaml`, such as `msimulizi-explainer` or `msimulizi-narrator-sw`. |
| **`gpt-5.4`** | Higher-quality model used for Swahili narration. |
| **`gpt-5.4-mini`** | Lower-latency model used for the explainer, verifier, English/French narration, and spoken-script adapter. |
| **Azure AI Speech** | TTS service. Production uses managed identity or a key depending on `KEY_MODE`. |
| **Azure AI Content Safety** | Moderation for narration and corrections. |
| **Azure Cosmos DB** | Persistence for snapshots, moments, cards, audit entries, corrections, and review records. Already provisioned; the app uses it rather than an in-memory-only store in production. |
| **Azure Container Apps** | Hosts the backend API and the Next.js frontend. |
| **Revision** | An immutable Container App revision. The live backend has one active revision at 100% traffic. |
| **Replica** | A running instance. The backend is pinned to **1** replica until a shared session/WebSocket backplane exists. |
| **Scale-to-zero** | Disabled for the backend. The demo should not cold-start between viewers. |
| **Azure Container Registry (ACR)** | Stores the backend and frontend images. |
| **Azure Blob Storage** | Stores generated audio. |
| **Azure Key Vault** | Stores `mcp-api-key` and `reviewer-api-key` for the live environment. Values never go in the repo. |
| **Application Insights / OpenTelemetry** | Metrics and traces for card/audio latency, verdict counts, and errors. |
| **Managed identity** | The production identity used for Foundry, Speech, Cosmos, Blob, and Key Vault access. |
| **Budget alert** | The Azure Consumption budget for the resource group. It is a guardrail, not a hard cap. |
| **Bicep** | `infra/main.bicep` and modules. CI compiles/validates; it does not deploy. |
| **`azd`** | The operator workflow for manual deployment. CI does not run `azd up`, `azd deploy`, or provisioning. |
| **Local-only runbooks** | `docs/azure-production-guide.md` and `docs/azure-resources-and-env.md` exist on the operator’s machine, are gitignored, and are intentionally not part of the remote repository. |

---

## 6. Quality and review vocabulary

| Term | Meaning |
|---|---|
| **Groundedness eval** | `evals/groundedness_eval.jsonl` plus `evals/results/groundedness_latest.json`. The current artifact is a 50-entry heuristic pass at 1.0. |
| **Heuristic score** | A deterministic check of structure/evidence, not a human quality judgment. It is not a substitute for native review. |
| **Native-speaker review** | A fluent Swahili speaker scoring captions for fluency, idiom/register, and faithfulness. |
| **Blocking issue** | Wrong player/team/minute/score/metric, missing gloss, fabricated fact, unsafe language, or a number the voice will mispronounce. A blocking issue prevents approval. |
| **30-line threshold** | The minimum number of distinct signed-off lines before an average may be published. |
| **Sign-off export** | `scripts/export_swahili_review.py --min-lines 30`. It refuses to export below the threshold and holds out blocking/edited lines until second review. |
| **Second review** | A confirmation step for an edited/approved line. The dashboard records `requires_second_review`; the current demo does not automate the handoff. |
| **Reviewer key** | The secret that unlocks `/review`. It is not a score and must not appear on camera. |
| **No published average** | While the queue is below 30 signed-off lines, the README and pitch must not quote a native-quality number. |

---

## 7. Security and operations vocabulary

| Term | Meaning |
|---|---|
| **MCP** | Model Context Protocol surface at `/mcp/`. Production requires authentication. |
| **MCP API key** | The bearer token for MCP. Stored in Key Vault as `mcp-api-key`; consumed as `MCP_API_KEY`. |
| **Reviewer API key** | The key for reviewer-only routes. Stored in Key Vault as `reviewer-api-key`; consumed as `MSIMULIZI_REVIEWER_KEY`. |
| **CORS / allowed origins** | `MSIMULIZI_ALLOWED_ORIGINS` must include the frontend origin. |
| **`BACKEND_URL` / `WS_URL`** | Runtime frontend configuration for the API and WebSocket. |
| **Health check** | `GET /health` returns `ok`, `active_sessions`, `cosmos`, and `mcp` status. |
| **Read-only CI** | `.github/workflows/ci.yml` runs tests/checks but has no Azure login, provision, or deploy step. |
| **Manual deployment** | An explicit operator action (`azd deploy backend` / `azd deploy frontend`) after checks and review. |
| **Secrets hygiene** | No `.env`, keys, tokens, connection strings, or local-only runbooks in git. `python scripts/check_repo_hygiene.py` enforces the repository rules. |

---

## 8. How-to index

### 8.1 Run the app locally

```bash
cp .env.example .env
cp frontend/.env.local.example frontend/.env.local
python -m pip install -e ".[dev]"

# backend
uvicorn api.main:app --reload --port 8000

# frontend, in another terminal
cd frontend
npm ci
npm run dev
```

Open <http://localhost:3000>. Offline mode falls back to in-memory state and
template narration. No Azure credentials are required for the tests.

### 8.2 Run the checks

```bash
ruff check .
pytest
python scripts/check_repo_hygiene.py
python -m generator.validate
python scripts/run_groundedness_eval.py --no-azure

cd frontend
npm run test
npm run build
```

CI runs these checks only. It does not deploy Azure resources.

### 8.3 Start a short demo

1. Open the viewer.
2. Select a storyline, language, mode, and club focus.
3. Select **30×** replay speed. The first key moment is at match minute 12, so
   it arrives after about 24 seconds at 30×.
4. Press **Start**.
5. Let the caption appear first. Audio follows after the caption.
6. Switch to **Analyst** to show the pitch heatmap, possession, field tilt, xG,
   tempo, and the event-derived team-stats table.

At `1×`, the same first key moment takes 12 minutes. Use `30×` for a video and
edit out the wait if needed.

### 8.4 Disable or enable the spoken rewrite

Set `AUDIO_SCRIPT_ENHANCE=false` to synthesize the approved caption verbatim.
Leave it unset or `true` to allow the grounded spoken rewrite. The card text is
unchanged in both cases.

### 8.5 Change or add a storyline

1. Add or edit a YAML file in `generator/storylines/`.
2. Add the matching label to `STORYLINES` in
   `frontend/src/components/ReplayPanel.tsx`.
3. Add any player suggestions in `STORYLINE_PLAYERS` in
   `frontend/src/app/page.tsx`.
4. Run `python generator/validate.py` and `pytest`.
5. Check the generated cards and glosses before using it on camera.

The generator falls back to a built-in default if a YAML file is missing, but
the frontend label and the calibration bands still need to agree.

### 8.6 Review Swahili lines

1. Open `/review`.
2. Unlock it with the reviewer key. Do not record the key.
3. Read the Swahili line and its English gloss.
4. Score fluency, idiom/register, and faithfulness from 1–5.
5. Record any blocking issue and an optional correction.
6. Submit. A submitted line is reviewed, not automatically approved.
7. Edited lines stay out of the export until a second reviewer confirms them.

The full rubric is in [`native-speaker-review.md`](native-speaker-review.md).

### 8.7 Export a signed-off review set

```bash
python scripts/export_swahili_review.py --min-lines 30
```

The script refuses to export below 30 distinct signed-off lines and excludes
blocking/edited lines that still need a second review. Do not publish an average
from a partial export.

### 8.8 Run the groundedness eval

```bash
python scripts/run_groundedness_eval.py --no-azure
```

This writes `evals/results/groundedness_latest.json`. The API reads that file
and returns `null` when no artifact exists; the UI shows `—`, not `0.0%`.

### 8.9 Check the live service

```bash
curl -s https://msim-msimulizi-demo2-backend.blackflower-72b7c0e4.eastus2.azurecontainerapps.io/health
```

Expect `ok: true`, and `cosmos` / `mcp` reported as `live` when reachable. MCP
without authentication should return `401` or a redirect followed by `401`.
Use `/mcp/` for a direct MCP POST; `/mcp` may redirect.

### 8.10 Find the logs and metrics

- Backend container logs: Azure Container Apps revision logs for
  `msim-msimulizi-demo2-backend`.
- Metrics and traces: Application Insights / OpenTelemetry.
- Review state: `/review` and the Cosmos review records.
- Groundedness: `evals/results/groundedness_latest.json` and the review
  dashboard tile.
- Audio failures: look for `[audio]` and `[audio-script]` log lines; the caption
  path is independent.

### 8.11 Rotate a key

Keys live in Key Vault (`mcp-api-key`, `reviewer-api-key`). Rotate them in Key
Vault, then update the consuming Container App secret/environment as a manual
operator action. Never put the value in a commit, a screenshot, or the README.
If a key is exposed, rotate it before recording.

### 8.12 Deploy deliberately

Deployment is a manual operator action, not a CI job. The local-only runbooks
contain the environment-specific commands. Keep them local; do not add them to
the remote repository. Before deploying:

- `ruff check .`, `pytest`, frontend tests/build, generator validation, hygiene;
- review the diff for secrets and local-only files;
- confirm the backend remains at one replica and scale-to-zero stays disabled;
- confirm `/health` and the review API after the revision is active.

---

## 9. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No card after Start | First key moment is at match minute 12; speed is 1× | Select 30× before Start; wait ~24s or restart with 30× |
| Card appears but no audio | Audio is generated after the caption; autoplay blocked; tab muted | Wait, unmute, check the audio toggle; captions are unaffected |
| Audio sounds like the caption | `AUDIO_SCRIPT_ENHANCE=false` or the rewrite fell back | Check the env flag; check `[audio-script] fallback:` logs |
| Clock jumps backwards | Old frontend or a stale anchor | Use the current build; the clock reducer clamps backward anchors |
| Review average missing | Fewer than 30 signed-off lines | Complete the queue; do not invent a score |
| `/review` locked | Missing/expired reviewer key | Use the Key Vault value locally; never show it on camera |
| `/health` shows `cosmos` or `mcp` down | Dependency outage or configuration drift | Use the recorded demo; investigate the dependency before going live |
| MCP returns `307` | Posted to `/mcp` instead of `/mcp/` | Use `/mcp/` |
| Frontend build fails after a lockfile change | Node/npm mismatch | Use the CI Node 24 line and the committed lockfile |
| Native review export refuses | Below 30 lines or blocking/edited lines open | Complete the queue and second reviews; do not bypass the gate |

---

## 10. Repository map

| Path | Responsibility |
|---|---|
| `api/` | FastAPI app, routes, WebSocket manager, pipeline runner, session/health endpoints. |
| `pipeline/` | Interpreter, Moment, Personaliser, Explainer, Narrator, Verifier, orchestrator. |
| `renderer/` | Card rendering, sanitization, fallback, audio bridge, emotion, SSML, speech text, spoken script. |
| `frontend/` | Next.js viewer, review dashboard, components, scheduler, session clock, tests. |
| `generator/` | Synthetic match generator, storylines, calibration validation. |
| `adapter/` | Event replay and streaming adapters. |
| `shared/` | Models, Foundry client, observability, session clock, config loading. |
| `mcp_server/` | Authenticated MCP tool surface. |
| `infra/` | Bicep modules for Container Apps, Cosmos, Speech, Foundry, Key Vault, budget. |
| `evals/` | Groundedness fixtures and latest result artifact. |
| `scripts/` | Hygiene checks, groundedness runner, review export, model comparison. |
| `docs/` | Product, architecture, review, demo, and glossary documentation. |

---

## 11. Local-only documents

The Azure production runbooks are intentionally kept on the operator’s machine:

- `docs/azure-production-guide.md`
- `docs/azure-resources-and-env.md`

They are gitignored and not linked from the README. Do not commit them, copy
their commands into public docs, or show them in the submission video. The
[`README.md`](../README.md) is the public setup surface; this glossary is the
public vocabulary surface.
