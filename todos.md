# Human TODOs

Things that need your hands, accounts, or judgement — a coding agent can't do these.
Updated as new tasks are implemented. Check items off as you go.

---

## Azure account and subscription

- [ ] Create an Azure subscription (or confirm an existing one has sufficient quota for Container Apps, Cosmos DB, Foundry, Speech, Content Safety, and Blob Storage)
- [x] Install the Azure Developer CLI: `curl -fsSL https://aka.ms/install-azd.sh | bash`
- [x] Install the Azure CLI: `curl -fsSL https://aka.ms/InstallAzureCLIDeb | sudo bash`
- [ ] Log in: `azd auth login` and `az login`
- [ ] Set deployment target: `azd env new dev` → set `AZURE_LOCATION` (recommend `eastus` — confirmed to have sw-KE and sw-TZ voices) and `AZURE_ENV_NAME=dev`
- [ ] Run first deployment: `azd up` from the repo root
- [ ] After deployment, copy output values (`COSMOS_ENDPOINT`, `FOUNDRY_ENDPOINT`, `SPEECH_ENDPOINT`, `KEY_VAULT_URL`, etc.) into your local `.env`
- [ ] Request a real Azure quota review before the live demo and reserve enough capacity for Container Apps, Cosmos DB, AI Foundry, Speech, and Content Safety to avoid launch-day throttling
- [ ] Add a launch check to confirm the deployed app and the live backend are reachable with the real env variables before demo day, using the exact frontend URL and the generated Azure endpoints

## Azure AI Speech — voice confirmation

- [ ] After `azd up`, set `SPEECH_API_KEY` in your shell and run:
  ```
  python scripts/verify_azure_deployment.py
  ```
  Confirm `sw-KE-ZuriNeural` and `sw-TZ-RehemaNeural` are listed as available.
  If they are missing, redeploy to a region that carries them (e.g. `westeurope`) and update `AZURE_LOCATION`.

## Microsoft Foundry — model retirement check

- [x] In the same `verify_azure_deployment.py` run above, confirm retirement dates for `gpt-4o:2024-08-06` and `gpt-4o-mini:2024-07-18` fall after 10 November 2026.
  Reference: https://learn.microsoft.com/en-us/azure/ai-services/openai/concepts/model-retirements
  If a model has been retired or will retire before 10 Nov 2026, update the version in `config/foundry_models.yaml` and `infra/main.bicep` and redeploy.

## Key Vault secrets

- [ ] After deployment, set real API key values (replace the PLACEHOLDER defaults written by Bicep):
  ```
  az keyvault secret set --vault-name <kvName> --name mcp-api-key     --value "<your-key>"
  az keyvault secret set --vault-name <kvName> --name reviewer-api-key --value "<your-key>"
  ```
- [ ] Copy those same values into your local `.env` as `MCP_API_KEY` and `REVIEWER_API_KEY`.

## Container registry

- [ ] Create an Azure Container Registry (ACR) — `azd` will do this if you add it to the Bicep, or create manually:
  ```
  az acr create --name msimuliziacr --resource-group <rg> --sku Basic
  ```
- [ ] Set `AZURE_CONTAINER_REGISTRY_ENDPOINT` in your azd environment to `msimuliziacr.azurecr.io`.

## Hackathon registration (task 1)

- [x] Register for the hackathon before **20 October 2026 at 12:00 pm PT** (10:00 pm EAT).
- [ ] Create the project entry in Innovation Studio once the submission window opens on **6 October 2026**; select the *Inside the Game* challenge.
- [ ] Confirm the public GitHub repository's first commit is dated after **29 September 2026**.

## Open-data calibration (task 9)

- [ ] Run `python scripts/calibrate_from_open_data.py` locally (needs internet access to download StatsBomb Open Data).
  The script deletes raw files after extracting aggregates — no raw data will remain in the repo.
- [ ] Run `python scripts/train_xg.py` to produce `shared/xg_coefficients.json`.
- [ ] Review `DATA_PROVENANCE.md` for accuracy before committing.
- [ ] Commit the generated `generator/calibration_aggregates.json` and `shared/xg_coefficients.json` (aggregate stats only — no raw data) once calibration has been run.

## MCP server (task 26)

- [ ] Set `MCP_API_KEY` in your local `.env` and in Key Vault (see Key Vault secrets section above) so the MCP tools reject unauthenticated requests in production.
- [ ] Run `uv run pytest tests/test_mcp_server.py -v` to confirm all MCP server tests pass against the fake Cosmos/pub-sub.
- [ ] After deployment, verify the MCP server is reachable at `https://<app-url>/mcp` with a valid Bearer token using a tool like `curl` or the Kiro MCP panel.

- [ ] Run `python scripts/compare_swahili_models.py` after Foundry deployments are live.
  This writes `evals/swahili_comparison.json`.
- [ ] Share `evals/swahili_comparison.json` with a native Swahili speaker.
- [ ] Based on their feedback, update `config/foundry_models.yaml` → set `chosen_after_eval: true` on the chosen deployment.
- [ ] Author the first set of Swahili few-shot examples in `config/few_shots/sw.jsonl` (ideally with the native speaker).

## Native-speaker quality rating (task 29)

- [x] After the pipeline is running, collect at least **30 rated Swahili narration lines** through the `/review` page.
- [x] Record the average rating (target ≥ 4 / 5) in the README.
- [x] Add any approved correction edits to `config/few_shots/sw.jsonl`.

## Groundedness evaluation (task 29)

- [x] Populate `evals/groundedness_eval.jsonl` with 50 Key Moments and expected Claims Lists.
- [x] Run `python scripts/run_groundedness_eval.py` and confirm score ≥ 90 %.
- [x] Paste the score into the README.

## Pre-generated bundle (task 28)

- [ ] Run the bundle generator to produce `bundle/narrations/`, `bundle/audit/`, and `bundle/manifest.json`:
  ```
  python -m scripts.generate_bundle --offline
  ```
  Use `--offline` for a fast offline run with mock narrations. Drop the flag once Foundry and Speech are live to get real audio URLs in the manifest.
- [ ] Commit the generated `bundle/` directory so the app can seed the narration cache and serve fallback cards without any Azure calls.

## Deployment hardening (task 31)

- [ ] Set `CORS_ALLOWED_ORIGIN` in `.env` and Key Vault to the exact deployed frontend URL (not `*`) before going public.
- [ ] Configure Azure spending cap / budget alert for the subscription to cover until **10 November 2026 at 11:59 pm PT**.
- [ ] Load-test the live deployment with the concurrent session cap to confirm p50 ≤ 5 s and p95 ≤ 10 s.
- [ ] Run the live demo end to end with no login and confirm it defaults to the bundle replay and survives quota exhaustion.

## Demo video (task 34)

- [ ] Read `docs/video-script-guide.md` for the full shot list, timing breakdown, and recording tips.
- [ ] Record a video **≤ 2 minutes** following the 8-shot script in the guide.
  - English subtitles for all Swahili speech and on-screen text.
  - Fictional clubs and players only — no real names, no third-party trademarks.
  - No StatsBomb branding or copyrighted music (CC0 music only).
- [ ] Upload publicly to YouTube, Vimeo, Facebook Video, or Youku.
- [ ] Paste the video URL into the Innovation Studio submission form.

## Final submission (task 34 — hard deadline 27 October 11:59 pm PT / 28 October 09:59 EAT)

- [ ] Read `docs/pitch-deck-guide.md` for the slide structure, colour palette, and Innovation Studio pitch text template.
- [ ] Verify the GitHub repo is public and the README testing link works.
- [ ] Confirm the repo contains no personal data or secrets (run `scripts/check_repo_hygiene.py`).
- [ ] Write the pitch text in Innovation Studio: name every Microsoft/Azure technology used, what the project does, and the problem it solves; mention real-time intelligence, explainability, synthetic data innovation, narrative generation, and multi-language storytelling.
- [ ] Select the target categories and submit.

---

*Add new items here whenever a code task generates a step that requires your direct action.*
