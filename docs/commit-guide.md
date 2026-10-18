# Msimulizi — Commit Guide

Staged commit plan covering all work done since repository setup.
Run these in order. Each commit is atomic and passes CI on its own.

Rules:
- All commits must be dated after 29 September 2026 (enforced by `scripts/check_repo_hygiene.py`)
- No secrets, no raw data, no model files (`.pkl`, `.h5`, `.onnx`, `.tflite`)
- `frontend/.env.local` is gitignored by Next.js — do not commit it
- `bundle/` directory contents (narrations, audio) are committed only after the bundle generator runs with real Azure credentials (task 28)
- `.env` is gitignored — do not commit it

---

## Commit 1 — Repository bootstrap

```
git add LICENSE .gitignore README.md pyproject.toml azure.yaml
git add infra/main.bicep infra/main.parameters.json
git add .github/workflows/ci.yml
git add .env.example
git commit -m "chore: repository bootstrap, infra skeleton, CI workflow"
```

Covers: tasks 1, 2, 3, 4.

---

## Commit 2 — Shared types, profile key, numbers

```
git add shared/models.py shared/profile_key.py shared/numbers.py shared/__init__.py
git add tests/test_profile_key.py tests/test_numbers.py
git commit -m "feat(shared): core models, profile key, number format helpers"
```

Covers: task 2.

---

## Commit 3 — Cosmos DB, Foundry client, content safety, pub/sub, budget

```
git add shared/cosmos.py shared/foundry_client.py shared/content_safety.py
git add shared/pubsub.py shared/budget.py shared/session_clock.py
git add tests/test_cosmos.py tests/test_foundry_client.py tests/test_content_safety.py
git add tests/test_pubsub.py tests/test_session_clock.py
git commit -m "feat(shared): Cosmos repos, Foundry client, content safety, pub/sub, budget guard"
```

Covers: tasks 5, 6, 7, 8, 13.

---

## Commit 4 — xG model and data provenance

```
git add shared/xg.py shared/xg_coefficients.json
git add scripts/calibrate_from_open_data.py scripts/train_xg.py
git add generator/calibration_aggregates.json
git add DATA_PROVENANCE.md
git add tests/test_xg.py
git commit -m "feat(xg): logistic xG model, calibration aggregates, data provenance"
```

Covers: task 9.
Note: `generator/calibration_aggregates.json` contains aggregate stats only — no raw data.

---

## Commit 5 — Synthetic match generator

```
git add generator/generate.py generator/validate.py generator/validation_config.yaml
git add generator/storylines/
git add tests/test_generator.py
git commit -m "feat(generator): synthetic match generator, four storylines, validation script"
```

Covers: task 10.

---

## Commit 6 — Event source adapters

```
git add adapter/base.py adapter/factory.py
git add adapter/inprocess.py adapter/file_replay.py adapter/eventhubs.py
git add adapter/__init__.py
git add tests/test_adapter.py
git commit -m "feat(adapter): in-process, file-replay, and Event Hubs adapters"
```

Covers: task 11.

---

## Commit 7 — Interpreter, Moment agent, Explainer

```
git add pipeline/interpreter.py pipeline/moment.py pipeline/explainer.py
git add pipeline/__init__.py
git add moments/priority_config.yaml moments/__init__.py
git add explainer/theme_rules.yaml explainer/templates.yaml explainer/__init__.py
git add tests/test_interpreter.py tests/test_moment.py tests/test_explainer.py
git commit -m "feat(pipeline): Interpreter, Moment, and Explainer agents"
```

Covers: tasks 12, 14, 16.

---

## Commit 8 — Swahili model eval and few-shots

```
git add scripts/compare_swahili_models.py
git add evals/swahili_comparison.json
git add config/foundry_models.yaml
git add config/few_shots/sw.draft.jsonl config/few_shots/en.jsonl config/few_shots/fr.jsonl
git add tests/test_compare_swahili_models.py
git commit -m "feat(evals): Swahili model comparison, foundry model config, en/fr few-shots"
```

Covers: task 15.

---

## Commit 9 — Narrator, Verifier, Fallback, Personaliser

```
git add pipeline/narrator.py pipeline/verifier.py pipeline/personaliser.py
git add pipeline/recap_inputs.py
git add renderer/fallback.py renderer/fallback_templates.yaml
git add tests/test_narrator.py tests/test_verifier.py tests/test_personaliser.py
git commit -m "feat(pipeline): Narrator, Verifier, Fallback lines, Personaliser agents"
```

Covers: tasks 17, 18, 19.

---

## Commit 10 — Renderer, TTS, Orchestrator, API

```
git add renderer/renderer.py renderer/tts.py
git add renderer/stat_templates.yaml renderer/spotlight_templates.yaml renderer/__init__.py
git add pipeline/orchestrator.py
git add api/main.py api/routes.py api/websocket.py api/pipeline_runner.py api/__init__.py
git add mcp_server/server.py mcp_server/__init__.py
git add tests/test_renderer.py tests/test_tts.py
git add tests/test_api_hardening.py tests/test_mcp_server.py
git add tests/test_slice_integration.py
git commit -m "feat(api): Overlay Renderer, TTS, Orchestrator, REST+WS API, MCP server"
```

Covers: tasks 20, 21, 22, 23, 26.

---

## Commit 11 — Frontend viewer UI

```
git add frontend/src/
git add frontend/package.json frontend/tsconfig.json frontend/next.config.ts
git add frontend/vitest.config.ts frontend/postcss.config.mjs frontend/eslint.config.mjs
git add frontend/.gitignore frontend/.env.local.example
git add frontend/public/
git commit -m "feat(frontend): Next.js viewer UI — card feed, clock, personalisation, review page"
```

Covers: tasks 25, 27.
Do NOT add `frontend/.env.local` — it is gitignored.

---

## Commit 12 — Pre-generated bundle

```
git add scripts/generate_bundle.py
git add tests/test_bundle.py
git commit -m "feat(bundle): pre-generated bundle generator and startup seeding"
```

Covers: task 28.

Once `scripts/generate_bundle.py --offline` has run cleanly (no warnings):
```
git add bundle/manifest.json bundle/narrations/ bundle/audit/
git commit -m "data(bundle): offline bundle for comeback_from_two_down seed 42"
```

---

## Commit 13 — Observability and quality reporting

```
git add shared/observability.py
git add scripts/run_groundedness_eval.py
git add evals/groundedness_eval.jsonl
git add evals/results/groundedness_latest.json
git add config/few_shots/sw.jsonl
git commit -m "feat(observability): OTEL metrics, groundedness eval, Swahili few-shots (4.2/5)"
```

Covers: task 29.

---

## Commit 14 — Integration tests (task 30)

```
git add tests/test_full_integration.py
git commit -m "test(integration): full end-to-end pipeline, dual-session, failure injection"
```

Covers: task 30.

---

## Commit 14a — Bug fixes from offline testing

Files changed while verifying offline functionality (pubsub cleanup, xG header
penalty, bundle generator dynamic mock, calibration progress bar):

```
git add shared/pubsub.py shared/xg.py
git add scripts/calibrate_from_open_data.py scripts/generate_bundle.py
git add generator/calibration_aggregates.json shared/xg_coefficients.json
git add tests/test_pubsub.py tests/test_full_integration.py
git commit -m "fix: pubsub subscriber cleanup, xG header penalty, bundle offline mock"
```

---

## Commit 15 — Deployment hardening (after azd up)

```
git add infra/main.bicep infra/main.parameters.json   # if updated post-deploy
git add .github/workflows/ci.yml                       # Docker build + azd deploy stages
git commit -m "feat(infra): deployment hardening, Docker build CI stage, rate limit tuning"
```

Covers: task 31.

---

## Commit 16 — README, architecture diagram, documentation

```
git add README.md DATA_PROVENANCE.md
git add docs/architecture-eraser-spec.md
git add docs/pitch-deck-guide.md docs/video-script-guide.md docs/commit-guide.md
git add frontend/src/app/about/page.tsx   # if updated with final attribution
git commit -m "docs: README architecture diagram, Eraser.io spec, pitch and video guides"
```

Covers: task 32.

---

## Commit 17 — Final pre-submission sweep

```
git add .env.example
git add todos.md
git commit -m "chore: final env example sync, todos updated"
```

Run before submission:
```bash
python scripts/check_repo_hygiene.py
uv run pytest
cd frontend && npm run test -- --run
python scripts/run_groundedness_eval.py --no-azure
```

All four must pass cleanly before tagging.

---

## Tagging for submission

```bash
git tag -a v1.0.0-submission -m "Hackathon submission — 27 October 2026"
git push origin main --tags
```

---

## Notes on what NOT to commit

| File / pattern | Reason |
|---|---|
| `.env` | Contains local secrets |
| `frontend/.env.local` | Contains local API URLs, gitignored by Next.js |
| `bundle/narrations/*.json` with real `audio_url` | Contains live Azure Blob URLs — commit the offline version only |
| `*.pkl`, `*.h5`, `*.onnx`, `*.tflite` | Model files — blocked by hygiene check |
| `generator/raw_data/` | Raw StatsBomb data — gitignored |
| `__pycache__/`, `.pytest_cache/` | Build artefacts |
