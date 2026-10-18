# Requirements Document

## Introduction

Msimulizi ("the narrator") is an AI-powered match intelligence system that transforms a stream of synthetic, football-realistic events into live, explainable commentary and overlay cards. It ingests events from a replay or live stream, interprets them into rolling match statistics, detects key moments, explains why each moment matters, and renders the output as timed JSON overlay cards alongside radio-style narration in Swahili, English, and French. Every viewer can personalise the experience by mode (analyst or casual fan), language, favourite club, favourite player, or metric focus. At full time the system generates an automated match recap.

The system is built on Microsoft Agent Framework with six cooperating agents plus a deterministic Overlay Renderer. The Interpreter, Moment, and Personaliser agents are deterministic components. The Explainer, Narrator, and Verifier agents are LLM-backed and hosted on Microsoft Foundry. All six agents share a single match state store. Narration is generated on demand per Profile Key (match, language, mode, club perspective) and cached at that key to control cost and latency.

All match data is synthetic and newly generated within the hackathon submission window. No real football match data, footage, or pre-existing code or model files are used.

---

## Glossary

- **Msimulizi** is the system name, Swahili for "the narrator", and refers to the complete platform described in this document.
- **Match Generator** is the standalone, seeded, reproducible module that produces synthetic football event streams from two fictional squads and a Scripted Storyline.
- **Event** is a single discrete match occurrence carrying event_id, match_id, period, minute, second, team, player, event_type, start and end coordinates on a 0 to 100 pitch, outcome, xG (for shots), pressure flag, and running score.
- **Match ID** is a deterministic identifier derived from the Scripted Storyline identifier and the integer seed, so that every Replay Session of the same storyline and seed shares the same match_id and therefore the same cached narration.
- **Match State** is the rolling aggregate maintained by the Interpreter Agent, comprising possession share, field tilt, shots, cumulative xG per team, pressure rate, Momentum Score, and tempo.
- **Key Moment** is a detected occurrence of high significance. Each triggering Event produces exactly one Key Moment, which carries one or more trigger tags (goal, red_card, big_chance, momentum_swing, lead_change, player_milestone) and an optional late_game tag when the Event occurs after minute 75.
- **Structured Explanation** is a language-neutral internal object attached to every Key Moment, containing a theme (control_vs_chaos, pressure_change, or rhythm_shift), a reason, a numeric_evidence list of metric name and value pairs from the Match State, and an evidence_event_ids list. The reason is a single English sentence on why the moment matters, written by the Explainer Agent using only the numeric_evidence and evidence_event_ids. It is internal scaffolding and is never displayed directly; the Narrator Agent localises it into viewer-facing text.
- **Narrator Response** is the structured object returned by the Narrator Agent for each Profile Key, containing a headline (60 characters or fewer in the target language), a body (140 characters or fewer in the target language), a claims_list, and, for Swahili responses, a gloss_en object holding an English headline and body that faithfully translate the Swahili text under the same length limits.
- **Claims List** is a machine-readable list of the verifiable facts stated in a Narrator Response. Each claim has a claim_type (player, minute, score, metric, or event_id) and a value. Metric claims carry a metric name and numeric value. All numbers are written as digits and all player names exactly as in the event record.
- **Text Consistency Check** is the deterministic comparison of every digit sequence and player name appearing in a Narrator Response's headline, body, and gloss_en against its Claims List, in both directions.
- **Overlay Card** is a machine-readable JSON object timed to the match clock, containing card_id, match_clock, display_from, display_duration_ms, card_type, priority, player reference, team reference, headline and body text keyed by language code, gloss_en (for Swahili cards), the Structured Explanation, evidence_event_ids, a stat payload, a profile_key field, and a field marking the content as synthetic and AI-generated. It is suitable for rendering as a broadcast lower-third graphic.
- **Profile Key** is the cache key for a narrated Overlay Card, defined as the tuple (match_id, language, mode, club_perspective). Cards at the same Profile Key share narrated text. The Personaliser applies player spotlight and metric focus at display time without re-invoking the Narrator Agent.
- **Club Perspective** is one of home, away, or neutral, derived from the viewer's favourite club setting. Home or away perspectives adjust the framing of shared moments toward the respective team.
- **Viewer Profile** is the set of personalisation dimensions: mode (analyst or casual), language, favourite club (mapped to a Club Perspective), favourite player, single metric focus, and audio-only flag.
- **Interpreter Agent** is the deterministic component that consumes Events and maintains the Match State.
- **Moment Agent** is the deterministic component that detects Key Moments from the Match State, ranks them, and emits Key Moment records.
- **Explainer Agent** is the LLM-backed agent that writes the reason for each Structured Explanation. Theme selection, numeric_evidence, and evidence_event_ids are assembled deterministically before the LLM is invoked.
- **Narrator Agent** is the LLM-backed agent that renders a Structured Explanation into a Narrator Response in the requested language and mode.
- **Personaliser Agent** is the deterministic component that applies Viewer Profile dimensions to rank and filter Key Moments and sets the Club Perspective for the Narrator Agent, without invoking an LLM.
- **Verifier Agent** is the LLM-backed agent that first runs a deterministic pre-check (claim validation and the Text Consistency Check) and then invokes the LLM to check semantic grounding of anything the pre-check cannot cover.
- **Overlay Renderer** is the deterministic code that converts Verifier-approved Narrator Responses into timed Overlay Cards, schedules them, and writes them to the durable store.
- **MCP Server** is a Model Context Protocol server exposing typed tools (get_match_state, list_key_moments, get_player_stats) so external agents can query the current Match State.
- **xG** is Expected Goals, a value between 0 and 1 representing shot-scoring probability, computed from shot distance, angle, header flag, and penalty flag using a logistic regression trained from scratch during the hackathon window on aggregate statistics derived from permitted open data sources.
- **Field Tilt** is the share of a team's passes occurring in the opposition's final third, used as a proxy for territorial dominance.
- **Momentum Score** is a per-team score from 0 to 100, computed over a 10-minute sliding window from the weighted sum of shots, cumulative xG, pressure events, and possession changes. A momentum swing occurs when the difference between the two teams' Momentum Scores changes by 15 points or more over the same window.
- **Priority Rank** is an integer from 1 to 5 assigned to each Key Moment, where 1 is highest. Goals and red cards are always Priority Rank 1 and are never suppressed by any Viewer Profile filter.
- **Replay Mode** is an operating mode in which the system streams a pre-generated synthetic match at configurable speed, used as the primary demo and judging path.
- **Replay Session** is an isolated per-viewer replay instance with its own match clock, so that one viewer's storyline selection or replay restart does not affect any other viewer's session.
- **Scripted Storyline** is a pre-defined match narrative (for example a comeback from two goals down) that drives the Match Generator to produce a predictable, drama-rich event sequence.
- **Groundedness** is the property of a Narrator Response in which every entry in the Claims List traces directly to the event record or to the Structured Explanation, and the text states nothing outside the Claims List.
- **Verifier Verdict** is the Verifier Agent's pass or fail decision on a Narrator Response, stored with it in the audit log.
- **Fallback Line** is a deterministic, template-generated narration line, localised in all three languages with an English gloss for Swahili, emitted when the Narrator Agent fails or the Verifier Agent rejects two consecutive attempts.
- **Stat Card** is an Overlay Card with card_type "stat", rendered by deterministic code from Match State values using localised label strings from a translation file, with no LLM involvement, followed by an Azure AI Content Safety check.
- **Spotlight Card** is an Overlay Card with card_type "player_spotlight", rendered by deterministic code when the viewer's favourite player is involved in a notable event, using localised templates and no LLM involvement, followed by an Azure AI Content Safety check.
- **Cached Narration** is a previously generated Overlay Card stored per Profile Key and served whenever that Profile Key has been generated before or model quota is unavailable.
- **Pre-generated Bundle** is the set of Overlay Cards, Claims Lists, Verifier Verdicts, and audio files covering all 18 Profile Keys (3 languages, 2 modes, 3 club perspectives) for the bundled default Scripted Storyline. Cards, Claims Lists, and Verdicts are committed to the repository. Audio is stored in Azure Blob Storage and referenced from a committed manifest with checksums, with the generation script in the repository.
- **End-to-End Latency Budget** is the total time from Event receipt to Overlay Card delivery, with targets of p50 at or under 5 s to card, p95 at or under 10 s to card, and p50 at or under 8 s to audio. Per-component allocations are: adapter forwarding 100 ms, Interpreter 200 ms, Moment 300 ms, Explainer 1 s, Narrator 1.5 s on the first attempt plus 1.5 s on a retry, Verifier pre-check 200 ms plus LLM check 1 s per pass, Content Safety 300 ms, Renderer 100 ms. Audio synthesis adds up to 3 s after card delivery. The single-retry path fits within the p95 target.
- **Correction Loop** is a UI feature allowing any viewer to record a thumbs-up or thumbs-down rating on a narration line. Viewers may also submit a text edit, but edits enter a review queue and join the Narrator Agent's few-shot set only after an authorised reviewer approves them and Azure AI Content Safety passes the edited text.
- **Microsoft Foundry** is Microsoft's platform for model hosting, orchestration, evaluation, and management, used as the primary AI platform for Msimulizi.
- **Agent Framework** is Microsoft Agent Framework, the orchestration layer used to host and coordinate the six agents.

---

## Requirements

### Requirement 1: Synthetic Match Generation

**User Story:** As a developer, I want a seeded, reproducible match generator that produces football-realistic synthetic event streams, so that the system always has controlled, compliant demo data that never relies on real match footage or licensed data.

#### Acceptance Criteria

1. THE Match Generator SHALL produce an event stream with pass counts, completion rates, shot counts, and goal counts that fall within calibration bands defined per Scripted Storyline in a validation configuration file.
2. THE Match Generator SHALL support at least 4 Scripted Storylines: a comeback from two goals down, a red card that shifts control, a late equaliser, and a dominant side that loses.
3. WHEN the Match Generator is invoked with the same integer seed and the same Scripted Storyline, THE Match Generator SHALL produce an identical event sequence on every invocation, with a match_id derived deterministically from the storyline identifier and the seed.
4. THE Match Generator SHALL assign fictional club names and fictional player names to all events such that no name matches any real-world professional football player or club, past or present.
5. THE Match Generator SHALL emit match metadata as the first event of every stream, including both team names, squad lists, formations, and kickoff time.
6. THE Match Generator SHALL compute xG for every shot event using the same shared xG function used by the Interpreter Agent.
7. WHEN the validation script is run against a generated match, THE validation script SHALL exit with a non-zero code if any calibration target drifts outside its storyline-specific tolerance band defined in the validation configuration file.

---

### Requirement 2: Event Ingestion and Replay

**User Story:** As an operator, I want a swappable event source adapter and an isolated per-viewer replay session, so that demo replays are stable and judges can explore storylines independently without interfering with each other.

#### Acceptance Criteria

1. THE Event Source Adapter SHALL accept events from a local file replay, an Azure Event Hubs stream, or a configurable in-process generator, selected by a single environment variable with no code changes to the agents.
2. WHEN operating in Replay Mode, THE Event Source Adapter SHALL emit events at a configurable playback speed expressed as a multiplier of real match time, settable without redeployment.
3. WHEN an event is received, THE Event Source Adapter SHALL forward the event to the Interpreter Agent within 100 milliseconds of receipt.
4. IF the event source connection is interrupted for more than 5 seconds, THEN THE Event Source Adapter SHALL log the interruption with a timestamp and resume forwarding from the last successfully delivered Event on reconnection.
5. THE system SHALL create an isolated Replay Session per viewer, each with its own match clock, so that one viewer's actions do not affect any other viewer's session state.

---

### Requirement 3: Match State Interpretation

**User Story:** As a broadcast analyst, I want a continuously updated match state that tracks possession, field tilt, xG, pressure, momentum, and tempo, so that every Key Moment and Explanation is grounded in live match context.

#### Acceptance Criteria

1. WHEN an event is received, THE Interpreter Agent SHALL update the Match State within 200 milliseconds of receiving that event.
2. THE Interpreter Agent SHALL track possession share, Field Tilt, cumulative xG for each team, pressure events per minute over a 5-minute sliding window, a Momentum Score (0 to 100 scale) per team over a 10-minute sliding window, and tempo (events per minute) over a 5-minute sliding window.
3. THE Interpreter Agent SHALL accumulate pass distance and pass accuracy per player and per team, tagging each pass event with the player's name, updated after every pass event.
4. WHEN the Match State is updated, THE Interpreter Agent SHALL publish the updated state to the MCP Server within 500 milliseconds.

---

### Requirement 4: Key Moment Detection

**User Story:** As a broadcaster, I want the system to detect and rank key moments automatically without duplicates, so that commentary and overlay cards are triggered once for each moment that matters, without manual curation.

#### Acceptance Criteria

1. THE Moment Agent SHALL detect the following triggers: goal, red card, big chance (xG of 0.40 or more), momentum swing (the difference between the two teams' Momentum Scores changes by 15 points or more over a 10-minute window), lead change, and player milestone (first shot on target, hat-trick, tenth pass into the final third).
2. WHEN several triggers arise from the same Event, THE Moment Agent SHALL emit a single Key Moment carrying all applicable trigger tags, and WHEN the Event occurs after minute 75, THE Moment Agent SHALL add the late_game tag.
3. THE Moment Agent SHALL assign default Priority Ranks of 1 to goals and red cards, 2 to big chances and lead changes, 3 to momentum swings, and 4 to player milestones, and SHALL raise a Key Moment carrying the late_game tag by one level where it is not already Priority Rank 1. A Key Moment with several tags takes the highest rank among them.
4. THE Moment Agent SHALL emit at most one momentum swing Key Moment per 10 match minutes.
5. THE Moment Agent SHALL emit a Key Moment record to the Explainer Agent within 300 milliseconds of detecting the triggering Event.
6. WHILE the match is in Replay Mode, THE Moment Agent SHALL detect Key Moments in the same sequence as they appear in the event stream for a given seed, preserving determinism across runs.

---

### Requirement 5: Explainability

**User Story:** As a fan, I want every key moment to include a grounded explanation of why it matters, so that I understand the tactical context and not just the scoreline.

#### Acceptance Criteria

1. WHEN a Key Moment record is received, THE Explainer Agent SHALL produce a Structured Explanation containing a theme, a reason, at least one numeric_evidence entry drawn from the current Match State, and at least one evidence_event_id.
2. THE Explainer Agent SHALL select the theme deterministically using rules and thresholds defined in a configuration file (control_vs_chaos from possession, Field Tilt, and Momentum Score gaps; pressure_change from pressure rate shifts; rhythm_shift from tempo shifts), and SHALL assemble numeric_evidence and evidence_event_ids deterministically before invoking the LLM.
3. THE Explainer Agent SHALL invoke the LLM only to write the reason as a single sentence using solely the supplied numeric_evidence and evidence_event_ids.
4. WHEN the reason is written, THE Explainer Agent SHALL deterministically verify that every number in it appears in numeric_evidence; IF verification fails, THEN THE Explainer Agent SHALL regenerate the reason once, and IF it fails again, SHALL use a deterministic template reason.
5. THE Explainer Agent SHALL store the Structured Explanation alongside the Key Moment record in the match state store.
6. IF the Explainer Agent cannot retrieve a required Match State value or complete the LLM call within 1 second, THEN THE Explainer Agent SHALL emit a Structured Explanation using a deterministic template reason and the evidence available, and SHALL flag the record as partially grounded in the audit log.

---

### Requirement 6: Narration and Language

**User Story:** As a Swahili-speaking fan, I want radio-style commentary written natively in Swahili, with English and French also available, so that I experience the match in my language rather than a translated version.

#### Acceptance Criteria

1. THE Narrator Agent SHALL generate narration for a given Profile Key by rendering the Structured Explanation into a Narrator Response (headline, body, and claims_list) in the requested language and mode, returning all fields in a single response.
2. THE Narrator Agent SHALL ground every narration line solely on the event minute, player names, event type, score state, and the reason, numeric_evidence, and evidence_event_ids of the Structured Explanation, and SHALL include no claims beyond those inputs.
3. THE Narrator Agent SHALL write all numbers as digits, write player names exactly as they appear in the event record, and list every such number and name in the Claims List.
4. WHEN the Viewer Profile mode is analyst, THE Narrator Agent SHALL include at least one numeric_evidence value from the Structured Explanation in the narration, listed as a metric claim.
5. WHEN the Viewer Profile mode is casual fan, THE Narrator Agent SHALL produce narration in plain, non-technical language within the length limits of the Narrator Response.
6. THE Narrator Agent SHALL generate Swahili narration natively, using few-shot examples of Swahili radio commentary style, and SHALL NOT produce it by translating English output.
7. WHEN the language is Swahili, THE Narrator Agent SHALL include in the Narrator Response a gloss_en that faithfully translates the Swahili headline and body, within the same length limits.
8. THE Narrator Agent SHALL generate a recap narration at full time for each requested Profile Key, covering the match summary.
9. WHEN a Profile Key has already been generated and cached, THE system SHALL serve the Cached Narration for that Profile Key and SHALL NOT invoke the Narrator Agent again.

---

### Requirement 7: Verification and Failure Recovery

**User Story:** As a system operator, I want every narration line verified for groundedness before it reaches viewers, with a fallback that keeps the feed running if verification fails, so that incorrect claims never reach the audience.

#### Acceptance Criteria

1. WHEN a Narrator Response is received, THE Verifier Agent SHALL run a deterministic pre-check that validates every Claims List entry against the event record and Match State, including metric claims against numeric_evidence.
2. THE Verifier Agent SHALL run the Text Consistency Check on the headline, body, and gloss_en, failing the response if any digit sequence or player name in the text has no matching claim, or if any player, minute, score, or metric claim value does not appear in the text.
3. IF the deterministic pre-check or the Text Consistency Check fails, THEN THE Verifier Agent SHALL emit a fail verdict immediately without invoking the LLM.
4. WHEN a Narrator Response passes the deterministic checks, THE Verifier Agent SHALL invoke the LLM to check that the narration is consistent with the reason and that the gloss_en faithfully translates the Swahili text, and SHALL emit a Verifier Verdict within the time allocated in the End-to-End Latency Budget.
5. IF the Verifier Agent emits a fail verdict, THEN THE Narrator Agent SHALL retry narration once, incorporating the rejection reason in its prompt.
6. IF the second narration attempt also receives a fail verdict, THEN THE Overlay Renderer SHALL emit a Fallback Line generated from a deterministic localised template using the Key Moment type, player name, and score state.
7. IF a model call to any LLM-backed agent does not return within 3 seconds, THEN THE system SHALL emit a Fallback Line and SHALL log the timeout with a timestamp, agent name, and Key Moment ID.
8. THE Verifier Agent SHALL store every Narrator Response, its Claims List, its Verifier Verdict, the evidence used, and a timestamp in an append-only audit log queryable by match_id.
9. WHEN model quota is unavailable, THE system SHALL serve the Pre-generated Bundle for the bundled default Scripted Storyline, and SHALL serve Fallback Lines for any other storyline, so the public demo URL continues to deliver Overlay Cards.

---

### Requirement 8: Overlay Rendering and Broadcast Output

**User Story:** As a broadcast engineer, I want every approved insight emitted as a machine-readable, timed JSON Overlay Card that is scheduled sensibly, so that it can drive graphical lower-third overlays on a live production feed without additional transformation.

#### Acceptance Criteria

1. THE Overlay Renderer SHALL emit an Overlay Card for every Verifier-approved Narrator Response, containing card_id, match_clock (period, minute, second), display_from, display_duration_ms, card_type (goal, key_moment, stat, player_spotlight, recap), priority, player reference, team reference, headline and body text keyed by language code (populated from the Narrator Response for LLM-generated cards and from localised templates for stat and player_spotlight cards), gloss_en for Swahili cards, the Structured Explanation, evidence_event_ids, stat payload, profile_key, and a synthetic_ai_generated boolean field set to true.
2. THE Overlay Renderer SHALL constrain headline text to 60 characters or fewer and body text to 140 characters or fewer per language, and IF a Narrator Response exceeds either limit, THEN THE Narrator Agent SHALL be prompted to regenerate rather than the text being truncated.
3. THE Overlay Renderer SHALL render Stat Cards and Spotlight Cards from deterministic localised templates over verified Match State values, pass the resulting text through Azure AI Content Safety, and write the card to Cosmos DB, with no LLM invoked for these card types.
4. THE Overlay Renderer SHALL emit a Stat Card at minutes 15, 30, 60, and 75, at half time, and at full time.
5. THE Overlay Renderer SHALL schedule at most one lower-third card on screen at a time per Replay Session; WHEN cards overlap, a card of higher Priority Rank SHALL pre-empt a lower one, a Priority Rank 1 card SHALL be queued rather than dropped if it cannot pre-empt, and lower-priority cards that miss their display window SHALL be dropped.
6. WHEN the match ends, THE Overlay Renderer SHALL emit a final recap Overlay Card within 10 seconds of the final whistle event, with card_type set to recap and the full-time match summary in the language of the requested Profile Key.
7. THE Overlay Renderer SHALL write each Overlay Card to Cosmos DB and SHALL expose a paginated REST API endpoint that returns all cards for a given match_id ordered by display_from, filterable by profile_key.

---

### Requirement 9: Personalisation

**User Story:** As a viewer, I want to tailor my experience by choosing my preferred language, mode, favourite club, favourite player, or a single metric to focus on, so that the same match intelligence feels made for me.

#### Acceptance Criteria

1. THE Personaliser Agent SHALL deterministically apply the Viewer Profile to every incoming Key Moment by mapping the favourite club to a Club Perspective (home, away, or neutral), applying metric-focus rules, and passing the Club Perspective and mode to the Narrator Agent as prompt context.
2. WHEN the Viewer Profile favourite club is set, THE Personaliser Agent SHALL set Club Perspective to home or away accordingly, which causes the Narrator Agent to frame shared moments from that team's viewpoint.
3. WHEN the Viewer Profile favourite player is set, THE Personaliser Agent SHALL flag notable events involving that player (goal, shot, assist, tackle won, interception, or card) so the Overlay Renderer emits a Spotlight Card, with at least 3 match minutes between Spotlight Cards for the same player except for goals and cards.
4. WHEN the Viewer Profile single metric focus is set, THE Personaliser Agent SHALL drop Key Moment cards of Priority Rank 4 or 5 that do not involve that metric, SHALL halve the display duration of such cards at Priority Rank 2 or 3, and SHALL never alter or suppress any Key Moment with Priority Rank 1.
5. WHEN the Viewer Profile audio-only flag is set, THE system SHALL deliver narration as audio via Azure AI Speech and SHALL make captions optional.
6. THE Personaliser Agent SHALL NOT invoke an LLM, and all ranking, filtering, and Club Perspective mapping SHALL be implemented as deterministic code.

---

### Requirement 10: Text-to-Speech and Audio Delivery

**User Story:** As a low-bandwidth radio listener, I want narration delivered as audio in my chosen language, so that I can follow the match without needing a screen.

#### Acceptance Criteria

1. THE system SHALL convert every approved Swahili narration line to audio using an Azure AI Speech neural voice in the sw-KE or sw-TZ locale, verified available in the deployment region before the feature is released.
2. THE system SHALL convert approved English and French narration lines to audio using Azure AI Speech neural voices for the respective locales.
3. THE system SHALL deliver audio for a Key Moment narration line within the audio latency target defined in the End-to-End Latency Budget.
4. IF an Azure AI Speech request fails or returns an error, THEN THE system SHALL display the text caption immediately and SHALL log the audio failure without blocking the Overlay Card feed.

---

### Requirement 11: MCP Server and State Exposure

**User Story:** As an external developer, I want to query the live match state through a Model Context Protocol server, so that I can build additional tools or agents on top of Msimulizi without coupling them to internal implementation details.

#### Acceptance Criteria

1. THE MCP Server SHALL expose at minimum the following typed tools with defined input and output schemas: get_match_state (returns the current Match State snapshot for a given match_id), list_key_moments (returns Key Moments for a given match_id with optional type and priority filters), and get_player_stats (returns per-player statistics for a given match_id and player name).
2. THE MCP Server SHALL reflect Match State updates within 1 second of the Interpreter Agent publishing a new state.
3. THE MCP Server SHALL require an API key for access and SHALL return a structured error for requests without a valid key.
4. THE MCP Server SHALL document all tool schemas in a format compatible with the Model Context Protocol specification.

---

### Requirement 12: Viewer UI

**User Story:** As a viewer, I want a clean web interface that shows the match clock, live overlay cards, my personalisation controls, and a replay panel, so that I can follow the match and adjust my experience in real time.

#### Acceptance Criteria

1. THE Viewer UI SHALL display the current match clock, score, and a simplified pitch visual showing the most recent event location, updated in real time.
2. THE Viewer UI SHALL render incoming Overlay Cards in real time, consuming the same timed JSON format used by the broadcast overlay path.
3. THE Viewer UI SHALL provide controls for language (Swahili, English, French), mode (analyst, casual fan), favourite club, favourite player, metric focus, and audio-only toggle.
4. THE Viewer UI SHALL display the gloss_en headline and body directly beneath every Swahili headline and body.
5. THE Viewer UI SHALL be keyboard-navigable and SHALL meet WCAG 2.1 AA colour contrast requirements for all text and interactive elements.
6. THE Viewer UI SHALL include a Correction Loop component that allows any viewer to rate a narration line (thumbs up or down) and optionally submit a text edit; submitted edits SHALL enter a review queue and SHALL only be added to the Narrator Agent's few-shot set after an authorised reviewer approves them and Azure AI Content Safety passes the edited text.
7. THE Viewer UI SHALL default to the bundled Scripted Storyline replay on the public demo URL and SHALL require no authentication to access.
8. THE Viewer UI SHALL include a replay control panel that allows a viewer to select a Scripted Storyline, set playback speed, and restart the replay, operating within the viewer's isolated Replay Session.
9. THE Viewer UI SHALL visibly indicate when a card comes from the Pre-generated Bundle and when it was generated live.

---

### Requirement 13: Responsible AI, Cost Control, and Enterprise Readiness

**User Story:** As an enterprise operator, I want the system to label all AI-generated content, enforce spending limits, maintain an audit trail, and protect secrets, so that it meets the standards required for production broadcast deployment and remains available throughout the judging period.

#### Acceptance Criteria

1. THE system SHALL label every Overlay Card and narration line as synthetic and AI-generated via the synthetic_ai_generated field defined in Requirement 8.1 and via a visible indicator in the Viewer UI.
2. THE system SHALL pass all LLM-generated text through Azure AI Content Safety before writing it to the overlay card store or delivering it to viewers, within the time allocation defined in the End-to-End Latency Budget.
3. THE system SHALL store all API keys and connection strings in Azure Key Vault and SHALL reference them via environment variables, with no secrets in the repository.
4. THE system SHALL maintain the append-only audit log defined in Requirement 7.8 and SHALL expose it to operators via a protected query API.
5. WHEN a Microsoft Foundry evaluation run is triggered, THE system SHALL report a groundedness score and SHALL flag the evaluation as failing if the score falls below 90 percent.
6. THE system SHALL enforce per-minute and per-day rate limits on all LLM and Speech API calls, serve Cached Narration when limits are reached, enforce a cap on concurrent Replay Sessions, and apply an idle session timeout of no more than 10 minutes, to prevent unbudgeted Azure spending.
7. THE system SHALL pre-generate all 18 Profile Keys for the bundled default Scripted Storyline, including audio, and SHALL publish the resulting Pre-generated Bundle as defined in the Glossary, so the public demo serves these cards at zero model cost and survives quota exhaustion.
8. THE system SHALL remain publicly accessible and free to test, with no authentication required for the public demo URL, until 10 November 2026 at 11:59 pm Pacific Time.
9. THE system SHALL report p50 and p95 latency metrics (event to caption and event to audio) in the README and on an operator dashboard.

---

### Requirement 14: Swahili Quality

**User Story:** As a Swahili-speaking fan, I want narration quality to be verified by a native speaker, so that the commentary sounds natural and credible rather than machine-translated.

#### Acceptance Criteria

1. THE system SHALL provide a native-speaker rating interface in the Correction Loop that records thumbs-up, thumbs-down, and optional edited text for a sample of Swahili narration lines, with only ratings from authorised reviewers counting toward the quality score.
2. THE repository README SHALL report a native-speaker quality score derived from rated Swahili lines, with a minimum acceptable score of an average of at least 4 out of 5 over at least 30 rated lines.
3. THE Narrator Agent SHALL incorporate accepted Correction Loop edits as few-shot examples for subsequent Swahili narration requests.

---

### Requirement 15: Testing and CI

**User Story:** As a developer, I want automated tests and a CI pipeline, so that regressions in the generator, state logic, and narration pipeline are caught before submission.

#### Acceptance Criteria

1. THE repository SHALL contain unit tests for the Match Generator (including match_id determinism), the shared xG function, the Interpreter Agent state aggregation logic, and the Moment Agent detection logic.
2. THE repository SHALL contain unit tests for Key Moment merging, Priority Rank assignment, and the momentum swing cooldown.
3. THE repository SHALL contain unit tests for the Verifier Agent's deterministic checks, covering a Claims List entry with a wrong player name, a wrong minute, a wrong score, a wrong metric value, and a missing Event ID, and Text Consistency Check failures in both directions (a number or name in the text with no claim, and a claim whose value is absent from the text).
4. THE repository SHALL contain unit tests for the failure recovery path, covering a single-retry sequence where the first attempt fails and the second passes, a double-fail sequence that triggers a Fallback Line, and a simulated model timeout that triggers a Fallback Line within the timeout window.
5. THE repository SHALL contain unit tests for the Overlay Renderer's card scheduling and for the Personaliser's Spotlight Card spacing and metric-focus rules.
6. THE repository SHALL contain an integration test that replays a full Scripted Storyline end to end and asserts that at least one Overlay Card of each card_type (goal, key_moment, stat, player_spotlight, recap) is produced.
7. WHEN the CI pipeline runs, THE pipeline SHALL execute the validation script against at least one generated match and SHALL fail the build if the validation script exits with a non-zero code.
8. THE repository SHALL contain a README in English with setup instructions, an architecture diagram, the reported p50 and p95 latency figures, the groundedness score from the most recent Foundry evaluation run, the native-speaker Swahili quality score, and the required data source attributions.

---

### Requirement 16: Data Provenance and Compliance

**User Story:** As a hackathon judge, I want clear documentation of every data source used, so that I can verify the project uses only synthetic data and complies with the Official Rules.

#### Acceptance Criteria

1. THE repository SHALL contain a DATA_PROVENANCE.md file that lists every external data source consulted during calibration, the specific aggregate statistics extracted, and an explicit statement that no raw event data was committed to the repository.
2. THE Match Generator SHALL use only fictional club and player names, and THE repository SHALL contain no raw event records, datasets, notebooks, or copied code derived from real football match data from any competition. Calibration from permitted open data sources SHALL exclude all Premier League competition files within those sources.
3. THE repository SHALL contain no code, scripts, notebooks, or model files (.pkl, .tflite, .onnx, or equivalent) that were created before 29 September 2026, and everything in the repository SHALL have been written or trained during the hackathon window.
4. THE xG regression model SHALL be trained from scratch during the hackathon window using only aggregate statistics derived from permitted open data sources, and DATA_PROVENANCE.md SHALL state the input features, training data source, and aggregate statistics used.
5. WHEN the StatsBomb Open Data terms require attribution, THE repository README and the application About page SHALL display the required StatsBomb attribution and logo, and THE demo video SHALL contain no StatsBomb-derived charts, branding, or trademarks.
