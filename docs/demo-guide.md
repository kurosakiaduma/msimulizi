# Msimulizi — Demo, Video, and Pitch Submission Guide

Current as of **27 October 2026**. This is the single source of truth for the
submission video, live pitch, and demo screenshots. The older
[`pitch-deck-guide.md`](pitch-deck-guide.md) and
[`video-script-guide.md`](video-script-guide.md) are historical visual
references; where they conflict with this guide, this guide wins.

> Check the live `/review` dashboard before recording. The native-speaker
> queue is **0/56** at the time of writing. Do not put a native-quality score
> on a slide until at least 30 distinct lines have a named reviewer sign-off.

---

## 1. What is live

| Item | Value |
|---|---|
| Viewer | <https://msim-msimulizi-demo2-frontend.blackflower-72b7c0e4.eastus2.azurecontainerapps.io> |
| Backend health | <https://msim-msimulizi-demo2-backend.blackflower-72b7c0e4.eastus2.azurecontainerapps.io/health> |
| WebSocket | `wss://msim-msimulizi-demo2-backend.blackflower-72b7c0e4.eastus2.azurecontainerapps.io/ws` |
| Review dashboard | `/review` on the viewer |
| MCP | `/mcp/` on the backend; authentication required |
| Public demo window | Free and available through **10 November 2026** |
| Backend capacity | One active revision, **one replica**, scale-to-zero disabled |
| Groundedness artifact | **1.0** on the shipped 50-entry heuristic eval |
| Native review | **0/56** lines; no average published |
| Synthetic data | Fictional clubs and players only; no third-party trademarks |

The backend is intentionally capped at one replica until a shared
WebSocket/session backplane exists. Do not pitch the current deployment as
horizontally scalable.

### What is deliberately not claimed

- No “native-quality Swahili” claim while the review queue is below 30 signed-off lines.
- No claim that the audio rewrite is separately native-reviewed. The 56-line queue covers caption cards; the audio-only rewrite inherits the caption’s facts and adds a short commentary beat.
- No claim of real player, club, or StatsBomb event data. The event stream is synthetic; aggregate calibration may reference open data, but no raw third-party match records are replayed.
- No claim that CI deploys Azure resources. CI is read-only; deployment is a manual operator action.

---

## 2. The 90-second demo story

The story is simple:

1. A synthetic match is running.
2. The caption appears first, with a Swahili line and an English gloss.
3. The audio arrives after the caption. It is a short commentary rewrite, not a
   word-for-word read of the card.
4. The same match can be viewed as an analyst, with a pitch heatmap and
   event-derived stats.
5. The quality loop is visible: a real reviewer queue, a groundedness artifact,
   and a hard 30-line gate before any average is published.

### Before you record

- Use Chrome at 1440×900, 100% browser zoom, sound on.
- Open the viewer and `/review` in separate tabs. Do not unlock `/review` on
  camera with a key visible.
- Select **Swahili**, **Casual Fan**, **Neutral**.
- Select **30×** replay speed. The first key moment is at match minute 12, so it
  arrives after about **24 seconds** of real time. At 1× it would take 12
  minutes; do not wait through that on camera.
- Put the microphone and system audio on separate tracks if possible.
- Hide terminals, `.env` files, Key Vault values, reviewer keys, and any Azure
  portal page that exposes a secret.

### Live run sequence

| Time | Action | What the viewer sees |
|---|---|---|
| 0:00 | Start on the viewer, storyline **Comeback from 2–0**, 30× | Score bar, pitch, replay controls |
| 0:05 | Press **Start** | Clock starts, event dots populate the pitch |
| 0:24 | First key-moment card arrives | Swahili headline, body, English gloss, source chips |
| 0:28 | Let the audio play | Short spoken commentary; captions remain on screen |
| 0:40 | Switch **Mode** to **Analyst** | Heatmap, possession, field tilt, xG, tempo, event-derived team stats |
| 0:55 | Wait for the next card or point at the live table | Analyst card and live match metrics |
| 1:05 | Cut to `/review` | Queue size, 0/56, groundedness 1.0, no published average |
| 1:20 | Cut to architecture slide | Foundry, Speech, Cosmos, Container Apps, managed identity |
| 1:30 | Close on the viewer and repo URL | Product name and links |

If the first card is late, keep the clock running and use a short time-lapse in
the edit. Do not fabricate a card or type a fake review score.

### The audio moment

The card text is the approved caption. The audio is generated **after** the
caption by a separate Foundry call that rewrites the card into one or two short
spoken sentences. The caption is never changed. For Swahili, the audio update
also carries an English gloss for the derived spoken line.

Example shape (not a script to read):

- Caption: *Gool! Asha Njeri anafunga. Dakika ya 31, ni 0-2.*
- Spoken line: *Gool! Asha Njeri anafunga, na wanaongoza kwa 0-2 sasa.*
- Added beat: the lead, which is directly supported by the score.

The rewrite is constrained by a no-new-facts prompt and a validator that rejects
new numbers, verbatim captions, missing Swahili glosses, and malformed output.
If the rewrite fails, the approved caption is spoken verbatim. To turn the
feature off, set `AUDIO_SCRIPT_ENHANCE=false`.

---

## 3. Video script (target 105 seconds)

Record at 1080p/30 fps. English voiceover. Add English subtitles for every
Swahili word that is spoken or visible. Do not use copyrighted music.

### 0:00–0:08 — Hook

**Screen:** Live viewer, Swahili card visible, subtle zoom.

**Voiceover:** “What if a football highlight could explain itself — in the
viewer’s language, with the receipts?”

### 0:08–0:18 — Problem

**Screen:** Quick cuts: score bar, a Swahili card, an analyst table.

**Voiceover:** “Most match intelligence is English-first, static, and opaque.
Msimulizi turns a synthetic event stream into live, explainable commentary in
Swahili, English, and French.”

### 0:18–0:30 — Start the match

**Screen:** Viewer, storyline selected, **30×**, **Start**.

**Voiceover:** “This is a synthetic match. Every club and player is fictional.
The pipeline watches goals, chances, red cards, and momentum shifts.”

### 0:30–0:47 — Caption first, audio second

**Screen:** First card. Hold on the Swahili headline and the English gloss. Let
the audio play for two or three seconds.

**Voiceover:** “The caption is the primary surface. Every Swahili line has an
English gloss. The audio is an enhancement: a grounded spoken rewrite, not a
word-for-word read of the card.”

### 0:47–1:02 — Analyst view

**Screen:** Switch to **Analyst**. Show the pitch heatmap, possession, field
tilt, xG, tempo, and the event-derived team-stats table.

**Voiceover:** “The same moment can be read as a casual fan or as an analyst.
The pitch, the heatmap, and the team stats come from the same event stream.”

### 1:02–1:15 — How it works

**Screen:** Architecture slide or the README Mermaid diagram, dark theme.

**Voiceover:** “Foundry agents interpret, select, explain, narrate, and verify.
Azure AI Speech voices the result. Cosmos DB persists the match, cards, audits,
and corrections. Container Apps hosts the API and viewer.”

### 1:15–1:30 — Quality loop

**Screen:** `/review` dashboard. Show the queue count, **0/56**, the
groundedness tile, and the sign-off rule. Do not type a score on camera.

**Voiceover:** “Automated checks catch groundedness and formatting problems.
They cannot certify natural Swahili. A fluent reviewer scores the queue, and we
publish no average until 30 distinct lines are signed off.”

### 1:30–1:40 — Resilience

**Screen:** Health endpoint, or a fallback/bundle card. Keep it brief.

**Voiceover:** “If a model call fails, the pipeline falls back instead of
stopping the match. The backend currently runs one replica; scaling wider needs
a shared session backplane.”

### 1:40–1:45 — Close

**Screen:** Product name, live demo URL, repository URL.

**Voiceover:** “Msimulizi. Live match intelligence, built on Azure.”

---

## 4. Pitch deck outline (8–10 slides)

Use the palette and typography from
[`pitch-deck-guide.md`](pitch-deck-guide.md). Keep one idea per slide. Every
number must be checked against the live dashboard on the day of submission.

### Slide 1 — Title

**Msimulizi — AI Match Intelligence**

“Live, explainable football commentary in Swahili, English, and French.”

### Slide 2 — Problem

- Match intelligence is English-first and hard to audit.
- Generic commentary does not adapt to language, club perspective, or depth.
- Swahili-speaking fans are under-served by real-time AI commentary.
- Existing tools show a score, not the reasoning behind a claim.

### Slide 3 — Insight

Captions are the trust surface; audio is the enhancement. If the caption is
grounded, glossed, and reviewable, the spoken layer can be more expressive
without becoming less accountable.

### Slide 4 — Product

Show three screens:

1. Swahili card with English gloss.
2. Analyst pitch heatmap and event-derived stats.
3. Review dashboard with the 0/56 queue and groundedness artifact.

### Slide 5 — How it works

Pipeline: **Interpreter → Moment → Personaliser → Explainer → Narrator →
Verifier → Renderer → WebSocket**. Add the audio adapter and the native-review
loop as side paths, not as extra agents.

### Slide 6 — Azure and agent design

- Azure AI Foundry: `gpt-5.4` for Swahili narration; `gpt-5.4-mini` for
  explainer, verifier, English/French, and the spoken-script adapter.
- Azure AI Speech: `sw-KE-ZuriNeural`, `sw-KE-RafikiNeural`,
  `sw-TZ-RehemaNeural`, `sw-TZ-DaudiNeural`; no `StyleList`, so expression comes
  from bounded prosody, event/perspective mapping, and short sentence breaths.
- Azure AI Content Safety.
- Azure Cosmos DB: state, cards, audits, corrections, review records.
- Azure Container Apps + Blob Storage + Key Vault + Application Insights.
- Microsoft Agent Framework for orchestration.
- Managed identity in production; authenticated MCP at `/mcp/`.

### Slide 7 — Grounding and review

- Deterministic checks for numbers, score, minute, and evidence.
- Verifier rejects unsupported claims.
- Perspective-aware narration for home / away / neutral profiles.
- Heuristic groundedness artifact: **1.0** on 50 entries (check live).
- Native-speaker review: **0/56** at the time of writing; no average until 30
  signed-off lines.
- The audio rewrite is constrained by a no-new-facts contract and falls back to
  the caption on failure.

### Slide 8 — Demo evidence

Use the same screenshots as the video. Add one callout:

> “Captions first. Audio second. Every Swahili card has an English gloss.”

Do not show a native-quality score unless the review queue has crossed the
threshold and a named reviewer has signed off.

### Slide 9 — Limits and next steps

- One backend replica until a shared WebSocket/session backplane exists.
- Native-speaker review is in progress; the current queue is visible, not
  hidden.
- Load testing for WebSockets, Speech, Foundry, Cosmos, and Blob egress is
  pending.
- Next: complete the review threshold, add the custom domain/CORS update, and
  load-test the live path.

### Slide 10 — Close

Live demo, repository, MIT licence, and contact. Include a QR code only if it
points to the current public URL and does not expose a reviewer key.

---

## 5. Screenshot and asset checklist

Capture these before editing:

- [ ] Viewer, Swahili casual card, gloss visible, audio player visible.
- [ ] Viewer, Analyst mode, pitch heatmap visible, team-stats table visible.
- [ ] Reviewer dashboard, queue count and **0/56** visible, no key visible.
- [ ] Groundedness tile, **1.0** or the current live value.
- [ ] Architecture diagram, dark theme, service labels readable.
- [ ] Health JSON, only if it does not expose secrets.
- [ ] Repository URL and live demo URL.

Do not include:

- reviewer keys, MCP keys, connection strings, or Key Vault values;
- Azure portal pages with subscription IDs or secrets;
- real club crests, player photos, StatsBomb branding, or copyrighted music;
- a fabricated review average or a fabricated “100% native quality” claim.

---

## 6. Submission checklist

- [ ] Public repository is current and the README matches the live product.
- [ ] `docs/glossary.md` is linked from the README.
- [ ] Video is ≤ 2:00, MP4/H.264, 1080p, with English subtitles for Swahili.
- [ ] Video URL is publicly viewable.
- [ ] Pitch deck is exported as PDF and uses the current model names and metrics.
- [ ] Live demo URL is reachable and `/health` returns `ok: true`.
- [ ] `/review` shows the real queue count; no average is claimed below 30 lines.
- [ ] Budget alert exists for the resource group.
- [ ] MCP without auth returns `401`.
- [ ] Backend still shows one replica and scale-to-zero disabled.
- [ ] No secrets, `.env` files, or local-only Azure runbooks are committed.
- [ ] CI is green and has no Azure deployment step.

---

## 7. Operator troubleshooting

### No card after Start

The first key moment is at match minute 12. At **30×** that is about 24 seconds.
At **1×** it is 12 minutes. Check the replay speed before restarting. If the
session is already running, wait or restart; the speed is locked for the
session.

### No audio

- Check the browser tab is not muted and the audio toggle is on.
- Audio arrives after the caption. Give it a few seconds.
- If the audio element shows an error, the caption is unaffected. Re-read the
  card or restart the session.
- To test verbatim audio, set `AUDIO_SCRIPT_ENHANCE=false` before starting the
  backend. The caption path is unchanged.

### Review dashboard is locked

The reviewer key is in Key Vault as `reviewer-api-key`; do not put it on screen.
If the key is unavailable, record the dashboard locked and explain the workflow
instead of inventing a score.

### Backend looks cold or unhealthy

Open `/health`. It should return `ok: true`, with `cosmos` and `mcp` reported as
`live` when the dependencies are reachable. If a dependency is down, use the
recorded video for the pitch and keep the live link as supporting evidence.

### A claim sounds too strong

Cut it. The project’s credibility comes from showing the real queue, the real
groundedness artifact, the real fallback behavior, and the real one-replica
limit. Do not trade that for a bigger number.
