# Implementation Plan

Build order notes. Foundations come first, then a thin end-to-end slice (task 24) before the full UI, bundle and polish. Every implementation task includes its own tests, written alongside the code and runnable offline against the Cosmos fake and `MockFoundryClient`. Overlay card scheduling (pre-emption, Priority Rank 1 queuing, stale-card drop) runs on the viewer's clock in the frontend, not on the server, so Requirement 8.5 should be read as applying to the delivery path. Target dates assume the 24 October feature freeze and a 26 October submission.

- [x] 1. Hackathon registration and repository setup
  - Register for the hackathon before registration closes on 20 October 2026, 12:00 pm PT (10:00 pm EAT); create the project entry when the submission window opens on 6 October and select the Inside the Game challenge
  - Create the public GitHub repository with the first commit made after 29 September 2026; add LICENSE, a `.gitignore` covering raw data folders and model-file patterns (`*.pkl`, `*.tflite`, `*.onnx`, `*.h5`), and a README stub
  - Do not copy in any earlier scripts, notebooks, data, or model files, including the earlier xG and video repository
  - _Requirements: 16.3_

- [x] 2. Repository structure, shared types, and profile key
  - Add LICENSE, a `.gitignore` covering raw data folders and model-file patterns (`*.pkl`, `*.tflite`, `*.onnx`, `*.h5`), and a README stub
  - Create the directory layout: `shared/`, `generator/`, `adapter/`, `pipeline/`, `renderer/`, `api/`, `mcp/`, `frontend/`, `infra/`, `scripts/`, `bundle/`, `evals/`, `config/`, `moments/`, `explainer/`
  - Define `shared/models.py` with `Event`, `EventType`, `MatchState`, `PlayerStats`, `KeyMoment`, `StructuredExplanation`, `NumericEvidence`, `NarratorResponse`, `Claim`, `GlossEn`, `OverlayCard`; `EventType` must include `metadata`, `period_start`, `half_time`, and `full_time` (the final whistle) in addition to the play events; shot events carry `is_header` and `is_penalty`
  - Define `shared/profile_key.py` with `make_profile_key(match_id, language, mode, club_perspective)` (dot-separated) and `parse_profile_key`
  - Define the canonical number-format helpers and `NUMBER_RE` in `shared/numbers.py` (percent, decimal, score, stoppage time, integer)
  - Write unit tests for profile key round trips and number formatting for all five formats
  - _Requirements: 1.3, 6.9, 8.1_

- [x] 3. Azure environment and infrastructure as code
  - Write `infra/main.bicep` for: Container Apps environment (backend minimum 1 replica with scale-to-zero off, plus frontend), Cosmos DB account with the six containers and their partition keys, create-only RBAC role for the audit container, container-level TTL enabled on `overlay_cards`, Key Vault (MCP and reviewer API keys), Blob Storage with a public-read audio container, Application Insights, a Microsoft Foundry account with the model deployments named in `config/foundry_models.yaml`, Azure AI Speech, Azure AI Content Safety, and managed identity role assignments
  - Write `infra/main.parameters.json` and `azure.yaml` for `azd`
  - Deploy a dev environment, then confirm that the Swahili voices (sw-KE and sw-TZ) are available in the chosen region and that the model versions in use have retirement dates after 10 November 2026
  - _Requirements: 10.1, 13.3, 13.8_

- [x] 4. CI skeleton
  - Write `.github/workflows/ci.yml` with lint (ruff), backend tests (pytest), frontend tests (Vitest), and the repository hygiene check; the validation script, Docker build, and `azd deploy` stages are added in tasks 10 and 31
  - Write `scripts/check_repo_hygiene.py`: fail the build if the repository contains model files (`.pkl`, `.tflite`, `.onnx`, `.h5`), raw data folders, secrets patterns, or commits dated before 29 September 2026
  - _Requirements: 15.7, 16.3_

- [x] 5. Cosmos repository layer
  - Implement `shared/cosmos.py` with typed repositories for the six containers: `match_state_snapshots` (upsert keyed by `(match_id, sequence_number)`), `key_moments`, `narration_cache`, `overlay_cards` (per-item TTL for spotlight cards), `audit_log` (create-only), `corrections`
  - Add exponential backoff with three retries, an in-memory write buffer retried every 60 seconds, and an in-memory fake used by all tests
  - Write unit tests for upsert idempotence, buffering after simulated failure, and create-only audit behaviour
  - _Requirements: 3.4, 7.8, 8.7_

- [x] 6. Foundry client, mock client, and budget guard
  - Implement `shared/foundry_client.py`: structured-output calls to named deployments from `config/foundry_models.yaml` (deployment names and pinned API versions), a 3-second asyncio timeout, and a typed `QuotaExceeded` error on Azure 429
  - Implement `MockFoundryClient` returning pre-scripted JSON for offline, deterministic tests
  - Implement `shared/budget.py`: per-minute and per-day token-bucket limits for LLM and Speech calls; when exhausted, raise `QuotaExceeded`; expose a `live_llm_allowed(speed)` check that disables live LLM calls above 4x replay speed
  - Write unit tests for timeout, 429 handling, limit exhaustion, and the speed rule
  - _Requirements: 7.7, 7.9, 13.6_

- [x] 7. Content Safety wrapper
  - Implement `shared/content_safety.py` wrapping Azure AI Content Safety, with a mock for tests
  - Define the shared block behaviour: return a typed `Blocked` result that callers handle (Key Moment cards substitute a Fallback Line, stat and spotlight cards are dropped, correction edits are rejected), always logging the event
  - Write unit tests for pass and block paths
  - _Requirements: 13.2_

- [x] 8. Pub/sub bus
  - Implement `shared/pubsub.py`: asyncio `PubSub` with `publish(topic, payload)`, `subscribe(topic) -> AsyncIterator`, and `latest(topic)` that returns the most recent retained payload so the MCP server can read state without a subscription
  - Write unit tests for fan-out, retained latest value, and subscriber cleanup
  - _Requirements: 3.4, 11.2_

- [x] 9. Open-data calibration, xG model, and data provenance
  - Implement `scripts/calibrate_from_open_data.py`: download the permitted open data into a gitignored folder, exclude all Premier League competition files, compute only aggregate statistics (pass completion by pitch zone, shot conversion by distance and angle, events per minute, pressure rates), write them to `generator/calibration_aggregates.json`, and delete the raw files
  - Implement `scripts/train_xg.py`: fit the logistic regression from the aggregate shot statistics and write `shared/xg_coefficients.json`
  - Implement `shared/xg.py` with `compute_xg(distance, angle, is_header, is_penalty) -> float`, loading coefficients from the JSON file
  - Write `DATA_PROVENANCE.md` listing every source consulted, the exact aggregates extracted, the xG input features and training source, the Premier League exclusion, and a statement that no raw data was committed
  - Write unit tests for `compute_xg` (parametrised shot geometries, penalty and header effects, output in 0 to 1)
  - _Requirements: 1.6, 16.1, 16.2, 16.4_

- [x] 10. Synthetic match generator
  - Implement `generator/generate.py`: `make_match_id(storyline, seed)` and `generate_match(storyline, seed) -> Iterator[Event]`; use `random.Random(seed)` exclusively; derive `event_id = f"{match_id}-{sequence:06d}"`; emit match metadata first, then `period_start`, `half_time`, and `full_time` events; set `is_header` and `is_penalty` on shots and call `shared.xg.compute_xg` for every shot; use only fictional club and player names
  - Implement the four Scripted Storyline YAML configs in `generator/storylines/` (comeback from two down, red card shift, late equaliser, dominant side loses)
  - Implement `generator/validation_config.yaml` with per-storyline calibration bands taken from the calibration aggregates
  - Implement `generator/validate.py` (exits non-zero on band drift) and add it to the CI workflow
  - Write unit tests for determinism (same seed and storyline give identical events and IDs), the event ID scheme, fictional-name checks, and the validation script's exit code when statistics are injected out of band
  - _Requirements: 1.1 to 1.7_

- [x] 11. Event source adapter
  - Define `adapter/base.py` with the `EventSourceAdapter` protocol: `async def events(session_id, speed) -> AsyncIterator[Event]`
  - Implement `adapter/file_replay.py` (JSONL replay at a speed multiplier, resume from last delivered event on reconnect), `adapter/inprocess.py` (streams `generate_match` output), and `adapter/eventhubs.py` (minimal consumer with checkpointing)
  - Implement `adapter/factory.py` selecting the adapter from the `EVENT_SOURCE` environment variable
  - Write unit tests for speed scaling, ordering, and resume after a simulated 5-second disconnect
  - _Requirements: 2.1 to 2.4_

- [x] 12. Interpreter Agent and Match State
  - Implement `pipeline/interpreter.py` as a deterministic class: consumes `Event`, updates the per-session in-memory `MatchState`, maintains sliding windows for momentum (10 minutes), pressure rate (5 minutes), and tempo (5 minutes), accumulates per-player pass distance and accuracy, and checks each shot's `xg` against `compute_xg`
  - Implement the Momentum Score exactly as specified in the design (window raw sums, clamped scores, difference now versus 10 minutes earlier, swing at 15 points or more)
  - Publish state to the pub/sub bus after every event; snapshot to Cosmos on Key Moments, every 2 match minutes, half time, full time, and reconnect
  - Write unit tests for possession, Field Tilt, xG totals, pass stats, and the momentum formula with explicit window scenarios
  - _Requirements: 3.1 to 3.4_

- [x] 13. SessionClock and lookahead
  - Implement `shared/session_clock.py`: `SessionClock` with `anchor_wall`, `anchor_match`, `speed`; `match_time()`; `update(new_speed)` and `restart()` that re-anchor the clock
  - Define the lookahead in wall-clock terms: the adapter emits events up to `viewer_match_time + 10 * speed` match seconds so the pipeline stays about 10 seconds of real time ahead at every speed
  - Define the `clock_update` message (`match_seconds`, `speed`, `anchor`) and the late-arrival policy fields carried on cards so the client can show late cards immediately or drop stale non-Priority-Rank-1 cards
  - Write unit tests for speed changes, restarts, and the lookahead at 0.1x, 1x, and 4x
  - _Requirements: 2.2, 2.5_

- [x] 14. Moment Agent
  - Implement `pipeline/moment.py`: consumes `(MatchState, Event)`, detects every trigger, merges all triggers on one Event into a single `KeyMoment` with tags, assigns Priority Rank from `moments/priority_config.yaml`, applies the late_game raise (floor of 1), enforces the momentum swing cooldown of 10 match minutes, and derives `moment_id = f"{match_id}-km-{sequence:04d}"`
  - Emit the `full_time` signal that triggers recap generation
  - Write `moments/priority_config.yaml` with default ranks (goal and red card 1, big chance and lead change 2, momentum swing 3, player milestone 4) and the xG threshold (0.40)
  - Write unit tests for tag merging, Priority Rank, late_game, the cooldown, and determinism across runs
  - _Requirements: 4.1 to 4.6_

- [x] 15. Swahili model comparison and baseline few-shots
  - Implement `scripts/compare_swahili_models.py`: generate 10 fixed Key Moments from seed 42, call each candidate Foundry deployment, and write outputs to `evals/swahili_comparison.json`
  - Run a native-speaker review of the outputs, choose the Swahili Narrator deployment, and record the decision in `config/foundry_models.yaml`
  - Author the first set of Swahili few-shot examples in `config/few_shots/sw.jsonl`; this task is required, not optional, because the model choice and few-shots feed the Narrator
  - _Requirements: 6.6, 14.2_

- [x] 16. Explainer Agent
  - Implement `pipeline/explainer.py`: return the existing `StructuredExplanation` for `(match_id, trigger_event_id)` from Cosmos without an LLM call if present; otherwise select the theme from `explainer/theme_rules.yaml`, assemble up to three `NumericEvidence` entries with `display_value`, collect `evidence_event_ids`, call the LLM to write a single-sentence `reason`, scan the reason with `NUMBER_RE` and require every token to be a `display_value` in the evidence, regenerate once, then fall back to `explainer/templates.yaml`; enforce the 1-second timeout with a template and `partially_grounded=True`
  - Write `explainer/theme_rules.yaml` and `explainer/templates.yaml` (one template per trigger type)
  - Write unit tests for cache skip, hallucinated-number detection (regenerate then template), and timeout fallback
  - _Requirements: 5.1 to 5.6_

- [x] 17. Narrator Agent, including recap
  - Implement `pipeline/narrator.py`: invoked per `NarrationRequest`; acquire a single-flight lock per `(profile_key, moment_id)`; build the prompt (system, few-shot, user turn); call the Foundry deployment with the structured output schema; validate the structure; require `gloss_en` for Swahili; write digits for all numbers, copy `display_value` verbatim, and return the Claims List; do not write to the cache (the Verifier does that)
  - Implement `pipeline/recap_inputs.py`: deterministically build a recap `StructuredExplanation` at `full_time` (final score, xG totals, possession, key moments) and add a recap mode to the Narrator prompt so each requested Profile Key gets a recap
  - Write English and French few-shot examples in `config/few_shots/` (Swahili from task 15) and include the approved corrections as additional Swahili few-shots
  - Write unit tests with `MockFoundryClient` for schema validation, single-flight (two concurrent requests give one LLM call), recap generation, and the length limits (60 and 140 characters)
  - _Requirements: 6.1 to 6.9_

- [x] 18. Verifier Agent, cache write, and Fallback Lines
  - Implement `pipeline/verifier.py` pre-check: validate every Claims List entry against the event record, Match State, and `display_value`s (including metric claims); run the bidirectional Text Consistency Check over headline, body, and `gloss_en` using `NUMBER_RE` and the player name list; run the length check; fail immediately without an LLM call on any pre-check failure
  - Implement the LLM check (narration consistent with the reason, `gloss_en` faithful) and the Verifier Verdict
  - Implement the retry contract: on fail, request one Narrator retry with the rejection reason; on a second fail or any model call over 3 seconds, emit a Fallback Line and log the timeout
  - On pass and Content Safety clear only, write the `NarratorResponse` to `narration_cache` with its audit `log_id`; write every response, pass or fail, to `audit_log` (create-only); never cache Fallback Lines
  - Implement `renderer/fallback.py` and `renderer/fallback_templates.yaml`: deterministic templates per `(moment_type, language)`, Swahili with `gloss_en`, using only player, minute, event type, and score
  - Write unit tests for wrong player, minute, score, and metric, a missing event ID, a digit in the text with no claim, a claim value absent from the text, a length failure, single retry then pass, double fail then Fallback, and timeout then Fallback
  - _Requirements: 7.1 to 7.8_

- [x] 19. Personaliser Agent
  - Implement `pipeline/personaliser.py`: receives the `KeyMoment` stream and the raw `Event` stream; maps `favourite_club` to `ClubPerspective`; derives Profile Keys; checks `narration_cache`; builds `NarrationRequest` objects for cache misses only; sends cache hits straight to the Renderer
  - Handle mid-match `profile_update` messages by deriving new Profile Keys for subsequent moments
  - Evaluate favourite-player spotlight eligibility on raw events using derived flags: `assist` (the scoring team's last successful pass by a different player within 5 match seconds before a goal) and `tackle_won` (a tackle with outcome success); notable events are goal, shot, assist, tackle won, interception, and card; enforce the 3-match-minute spacing except for goals and cards
  - Apply metric-focus rules (drop Priority Rank 4 and 5 cards without the metric, halve the display duration of rank 2 and 3 cards) and never alter Priority Rank 1
  - Write unit tests for spotlight spacing, derived flags, metric-focus rules, Priority Rank 1 protection, and profile updates
  - _Requirements: 9.1 to 9.6_

- [x] 20. Text-to-speech integration
  - Implement `renderer/tts.py`: call Azure AI Speech for approved narration; select the voice by language (sw-KE and sw-TZ voices as verified in task 3, then English and French voices); upload audio to Blob Storage keyed by a hash of language, voice, and text so repeated lines are reused; skip synthesis when the card already has an `audio_url`; publish an `audio_update` with `audio_url` and `match_seconds`; on failure, log and publish `audio_url=null`
  - Pre-generate audio for Fallback Line templates
  - Write unit tests with a fake Speech client for reuse, skip-when-present, and failure handling
  - _Requirements: 10.1 to 10.4_

- [x] 21. Overlay Renderer
  - Implement `renderer/renderer.py`: build `OverlayCard` from the Narrator Response or Fallback template; compute deterministic `card_id` (LLM cards from `profile_key` and `moment_id`; stat cards from `profile_key`, period, and minute; spotlight cards from `profile_key`, player, and `event_id`); store only `match_clock` and `display_duration_ms` (never `display_from`); apply durations by type (goal 8000, key_moment 6000, stat 4000, player_spotlight 5000, recap 10000 ms); publish the card with `match_seconds` to the pub/sub bus after the Cosmos write; start TTS in parallel
  - Implement Stat Cards at minutes 15, 30, 60, 75, half time, and full time from `renderer/stat_templates.yaml`, passing through Content Safety, with no LLM
  - Implement Spotlight Cards from `renderer/spotlight_templates.yaml` with a 24-hour TTL, passing through Content Safety, with no LLM
  - Emit the recap card within 10 seconds of the `full_time` event for each requested Profile Key
  - Write the stat and spotlight template files for Swahili (with `gloss_en`), English, and French
  - Write unit tests for card ID determinism and uniqueness across languages, no stored `display_from`, template rendering, Content Safety block handling, and recap timing
  - _Requirements: 8.1 to 8.4, 8.6, 8.7, 9.3_

- [x] 22. Orchestrator on Microsoft Agent Framework and app assembly
  - Implement `pipeline/orchestrator.py` with Microsoft Agent Framework: register the six agents (the deterministic ones as function components, the LLM-backed ones through the Foundry client), define the per-session workflow adapter, Interpreter, Moment, Personaliser, Explainer, Narrator, Verifier, Renderer, and wire the retry-once loop, Fallback path, and `QuotaExceeded` handling (serve cached narration or bundle, otherwise Fallback Lines)
  - Implement `api/main.py`: assemble the single FastAPI application (REST, WebSocket, FastMCP mounted at `/mcp`), startup and shutdown hooks (including bundle seeding from task 28), configuration from environment and Key Vault, and a session manager with a concurrent session cap and a 10-minute idle timeout
  - Wire OpenTelemetry hooks at every stage boundary for task 29
  - Write an in-process integration test using the mocks: one session replays a storyline and produces cards
  - _Requirements: 2.5, 13.6_

- [x] 23. REST API and WebSocket gateway
  - Implement `api/routes.py`: `POST /v1/sessions` (issues a server-side session ID and enforces per-IP and concurrent session caps before any WebSocket connects), `GET /v1/matches/{match_id}/cards`, `GET /v1/matches/{match_id}/state`, `GET /v1/audit/{match_id}/log` (reviewer key), `POST /v1/corrections`, `GET /v1/corrections/queue` (reviewer key), `PATCH /v1/corrections/{id}` (reviewer key); per-IP rate limiting middleware; Content Safety on correction edits; CORS limited to the deployed UI origin
  - Implement `api/websocket.py`: connect with the session ID; push cards with `match_seconds`, `audio_update`, `clock_update`, and event and score updates with `match_seconds` so the pitch and score follow the viewer clock; accept `profile_update`, speed, and restart commands; ping/pong heartbeat every 30 seconds; idle timeout at 10 minutes
  - Write unit tests for session cap enforcement, rate limiting, reviewer key checks, heartbeat, and clock messages
  - _Requirements: 2.5, 8.7, 12.7, 13.4, 13.6_

- [x] 24. Checkpoint: thin vertical slice (target 12 October)
  - Run a storyline end to end (generator, adapter, Interpreter, Moment, Personaliser, Explainer, Narrator, Verifier, Renderer, WebSocket) into a bare page that shows incoming cards, using at least one real Foundry call and one real Speech call
  - Confirm all tests pass and ask the user if questions arise before building the full UI

- [x] 25. Viewer UI core
  - Scaffold the Next.js 16 LTS (App Router) project in `frontend/` with Vitest, Lucide, Tailwind, Shadcn and RadixUI.
  - Implement a client-side clock driven by `clock_update` messages, and `<MatchClock>`, `<ScoreBar>`, and `<PitchVisual>` (SVG, event dot at `x_start`, `y_start`) that all render from the viewer clock, never from raw pipeline state
  - Implement `<ReplayPanel>` (storyline selector, speed slider 0.1x to 4x, restart) sending commands to the WebSocket
  - Implement `<CardFeed>` with the client-side priority scheduler: one card at a time, pre-emption by higher Priority Rank, Priority Rank 1 queued rather than dropped, stale lower-priority cards dropped, late cards shown immediately
  - Implement the `/` page wiring everything together, defaulting to the bundle replay on load
  - Write Vitest tests for the scheduler (pre-emption, Priority Rank 1 queue, stale drop, late arrival) and for clock handling across speed changes and restarts
  - _Requirements: 8.5, 12.1, 12.2, 12.7, 12.8_

- [x] 26. MCP server
  - Implement `mcp/server.py` with FastMCP and three typed tools: `get_match_state(match_id, session_id=None)`, `list_key_moments(match_id, trigger_tags=None, min_priority=None, limit=20)`, `get_player_stats(match_id, player_name, session_id=None)`; read state through `pubsub.latest` (within 1 second) and moments from Cosmos
  - Require the API key (`Authorization: Bearer`) and return a structured error without it; export the tool schemas; mount at `/mcp`
  - Write unit tests for each tool and for the missing-key error
  - _Requirements: 11.1 to 11.4_

- [x] 27. Viewer UI personalisation, accessibility, and review page
  - Implement `<PersonalisationPanel>` (language, mode, club, player, metric, audio-only) posting `profile_update` messages; show `from_bundle` and `synthetic_ai_generated` indicators on every card
  - Render `gloss_en.headline` and `gloss_en.body` directly beneath every Swahili headline and body
  - Implement `<CorrectionLoop>` (thumbs up or down, optional edit textarea, `POST /v1/corrections`), shown after a card has been displayed
  - Implement `/about` with the StatsBomb attribution and logo, data provenance summary, and AI disclosure (these appear in the README and About page only, never in the demo video)
  - Implement `/review` (API key gated) with the native-speaker rating queue, correction approval, groundedness score, and p50 and p95 latency charts
  - Apply WCAG 2.1 AA: semantic HTML, ARIA labels, visible focus outline, contrast-tested palette, keyboard navigation, and an audio-only mode showing only the clock and audio player
  - Write tests for gloss rendering, labels, keyboard navigation, and profile update messages
  - _Requirements: 12.3 to 12.6, 12.9, 13.1, 14.1_

- [x] 28. Pre-generated bundle
  - Implement `scripts/generate_bundle.py`: run `comeback_from_two_down` with seed 42 through the full pipeline for all 18 Profile Keys, write `NarratorResponse` records with their `audio_url` to `bundle/narrations/<profile_key>.json`, audit entries to `bundle/audit/<profile_key>.json`, upload audio to Blob Storage, and write `bundle/manifest.json` with deterministic `card_id`s, audio URLs, and SHA-256 checksums
  - Implement startup seeding: load the bundle's `NarratorResponse` records into `narration_cache` with `from_bundle=true` so bundle replay uses the normal cache-hit path; the Renderer reuses the stored `audio_url`; stat cards are rendered at runtime from templates
  - Serve the bundle when model quota is unavailable and Fallback Lines for any other storyline
  - Write unit tests for seeding, cache-hit rendering without LLM or TTS calls, and the quota-exceeded fallback
  - _Requirements: 7.9, 13.7_

- [x] 29. Observability and quality reporting
  - Instrument the backend with OpenTelemetry custom metrics (`card_latency_ms`, `audio_latency_ms`, verdict pass and fail counts, `fallback_count`, `quota_exceeded_count`) exported to Application Insights
  - Compute p50 and p95 latency, expose them on the `/review` dashboard, and write them to the README
  - Implement `scripts/run_groundedness_eval.py` with the `azure-ai-evaluation` SDK over `evals/groundedness_eval.jsonl` (50 Key Moments), write `evals/results/groundedness_latest.json`, fail below 90 percent, and report the score in the README
  - Run the native-speaker rating session over at least 30 Swahili lines, record the average (target 4 out of 5 or better) in the README, and add approved edits to `config/few_shots/sw.jsonl`
  - _Requirements: 13.5, 13.9, 14.2, 15.8_

- [x] 30. Full integration tests
  - Replay `comeback_from_two_down` with seed 42 end to end and assert at least one card of each type (goal, key_moment, stat, player_spotlight, recap)
  - Run two sessions at different match positions on the same `match_id` and assert independent MatchState, independent clocks, and shared narration cache hits with a single LLM call per Profile Key
  - Inject failures (Verifier fail, double fail, model timeout, Speech failure, Content Safety block, 429 quota) and assert the feed continues with the right fallback
  - Assert deterministic output: identical event IDs, Key Moment IDs, and card IDs across two runs of the same seed
  - _Requirements: 15.1 to 15.7_

- [x] 31. Deployment hardening and live-demo readiness (target 21 October)
  - Add the Docker build and `azd deploy` stages to the CI workflow (GitHub OIDC to Azure); deploy the backend with minimum 1 replica
  - Tune rate limits, the concurrent session cap, and budget alerts; load test with the session cap to confirm latency targets and cost
  - Confirm the demo works with no login, defaults to the bundle replay, and survives quota exhaustion; confirm model deployment retirement dates cover the period until 10 November 2026 11:59 pm PT and that Azure spending is capped for that period
  - Set `NEXT_PUBLIC_WS_URL` in `frontend/.env.local` to point at the deployed backend WebSocket endpoint once task 31 (deployment) is complete.
  - _Requirements: 13.6, 13.8_

- [x] 32. README, architecture diagram, and documentation
  - Write the English README: setup instructions, architecture diagram (export the Mermaid diagram with a light theme so titles are readable), data source attributions, p50 and p95 latency, groundedness score, native-speaker score, and a note that everything was built after 29 September 2026
  - Finalise `DATA_PROVENANCE.md` and the `/about` attribution
  - _Requirements: 15.8, 16.1, 16.5_

- [ ] 33. Checkpoint: feature freeze (24 October)
  - Ensure all tests, the validation script, the hygiene check, and the groundedness evaluation pass; stop adding features and fix only defects after this point

- [ ] 34. Submission (finish by 26 October; hard deadline 27 October 11:59 pm PT, which is 28 October 09:59 EAT)
  - Record a demo video under 2 minutes with English subtitles for all Swahili, using fictional clubs and players only, no third-party trademarks (including StatsBomb branding), and no copyrighted music; upload publicly to YouTube, Vimeo, Facebook Video, or Youku
  - Write the pitch text naming every Microsoft and Azure technology actually used, what the project does, and the problem it solves, and mention the areas covered (real-time intelligence, explainability, synthetic data innovation, narrative generation, multi-language storytelling)
  - Verify the public repository, the testing link with instructions in English, and that nothing contains personal data or secrets
  - Submit through the Innovation Studio project page, selecting the target categories
  - _Requirements: 13.8, 16.3, 16.5_