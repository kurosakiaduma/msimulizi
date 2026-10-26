# Msimulizi Azure Production Guide

This guide covers a controlled production deployment of Msimulizi to Azure
Container Apps using Azure Developer CLI (`azd`). It is intentionally explicit
about the checks that must be completed before making the demo public.

> **Current resource/env matrix:** see
> [`azure-resources-and-env.md`](azure-resources-and-env.md) for the exact
> resources, roles, environment variables, model versions, and preflight
> commands. This guide covers the operating procedure around that matrix.

## Deployment topology

`azd up` provisions and deploys:

- A backend Container App running FastAPI/Uvicorn.
- A frontend Container App running the Next.js production server.
- The Azure Container Apps environment and container registry.
- Cosmos DB, Blob Storage, Key Vault, Application Insights, Microsoft Foundry,
  Azure AI Speech, Azure AI Content Safety, and the managed identity defined in
  [`infra/main.bicep`](../infra/main.bicep).

The frontend is a browser application. It reads `BACKEND_URL` and `WS_URL`
from the server-side `/api/config` route at runtime, so the image does not need
to be rebuilt when the backend hostname changes. `NEXT_PUBLIC_*` values remain
only as local-development fallbacks.

## Before deployment

### Required local tools

- Azure CLI, authenticated with an account that can create the resources.
- Azure Developer CLI (`azd`).
- Docker, if building or publishing images manually.
- Node.js 20+ and Python 3.13+ for local validation.

### Required Azure decisions

Choose:

- A unique `AZURE_ENV_NAME`, such as `msimulizi-prod`.
- An Azure region that supports the selected Foundry deployment and the
  required Swahili Speech voices.
- A subscription and resource group policy that permits Container Apps,
  Container Registry, Cosmos DB, Storage, Key Vault, Application Insights,
  Foundry, Speech, and Content Safety.

Do not use production credentials in local `.env` files or commit them.

### Run the release checks

From the repository root:

```bash
uv sync --dev
uv run pytest -q
cd frontend
npm ci
npm run test
npm run lint
npm run build
cd ..
python generator/validate.py
python scripts/run_groundedness_eval.py --no-azure
```

The lint command may report warning-only findings. It must not report errors.
Run the repository hygiene check after the first commit exists:

```bash
python scripts/check_repo_hygiene.py
```

## Configure an `azd` environment

```bash
az login
azd auth login
azd env new msimulizi-prod
azd env set AZURE_ENV_NAME msimulizi-prod
azd env set AZURE_SUBSCRIPTION_ID <subscription-id>
azd env set AZURE_LOCATION eastus2  # verified for Cosmos, gpt-5.4, and sw-KE / sw-TZ
```

Review the generated environment values before provisioning:

```bash
azd env get-values
```

## Secrets and application configuration

The backend should use managed identity and Key Vault in Azure. Configure
secret references according to the resources created by
[`infra/main.bicep`](../infra/main.bicep), not by placing API keys in
`azure.yaml`, Bicep source, GitHub workflow files, or Docker build arguments.

`infra/main.bicep` creates placeholder Key Vault values only when
`KEY_MODE=bootstrap`. Rotate both secrets after the first deployment, then set
`azd env set KEY_MODE preserve` so later `azd up` runs do not overwrite the
rotated values.

At minimum, verify these production concerns:

- `FOUNDRY_ENDPOINT` and the selected model deployment are available.
- `SPEECH_ENDPOINT` has the intended `sw-KE` or `sw-TZ` voice.
- `CONTENT_SAFETY_ENDPOINT` is configured for generated text moderation.
- `COSMOS_ENDPOINT` and `COSMOS_DATABASE` point to the production account.
- `STORAGE_ACCOUNT_URL` / `AUDIO_BLOB_ACCOUNT_URL` and
  `AUDIO_BLOB_CONTAINER` are configured if audio is enabled.
- `APPLICATIONINSIGHTS_CONNECTION_STRING` is configured.
- `MSIMULIZI_REVIEWER_KEY` is a long, randomly generated secret.
- `MSIMULIZI_ALLOWED_ORIGINS` contains only the deployed frontend origin.
- Session, WebSocket, LLM, Speech, and per-IP rate limits are finite.

Do not expose reviewer, MCP, Foundry, Speech, Content Safety, Cosmos, or
Storage credentials as `NEXT_PUBLIC_*` variables.

## Frontend URL configuration

The browser fetches connection settings from the frontend's runtime
`/api/config` route handler. That handler reads the Container App environment
variables `BACKEND_URL` and `WS_URL` (set by `infra/main.bicep`) and returns:

```json
{"backendUrl": "https://<backend-fqdn>", "wsUrl": "wss://<backend-fqdn>/ws"}
```

Because the values are read at request time, the frontend image is no longer
environment-specific. `NEXT_PUBLIC_*` build arguments remain only as
local-development fallbacks and must not be relied on for production.

After deployment, verify the route from the public frontend URL:

```bash
curl --fail --show-error "$FRONTEND_URL/api/config"
```

If a custom domain is added, update `BACKEND_URL`, `WS_URL`, and
`MSIMULIZI_ALLOWED_ORIGINS` on the Container Apps, then create a new backend
revision. The backend CORS policy only allows the default frontend origin
computed by the template.

## Provision and deploy

After the preflight checks in
[`azure-resources-and-env.md`](azure-resources-and-env.md) pass:

```bash
azd provision
azd deploy
```

Or, for a first deployment:

```bash
azd up
```

The Container Apps are created with a temporary public bootstrap image because
the environment ACR is empty during the first provision. `azd deploy` then
pushes the real backend/frontend images and creates new revisions. Running
`azd provision` alone resets both apps to that bootstrap image; always follow
it with `azd deploy` (or use `azd up`).

The first provision attempt in `eastus` failed on 26 Oct 2026 with a Cosmos DB
capacity error. The working demo uses `eastus2`; check Cosmos regional capacity
before choosing a different region for a fresh deployment.

Capture the URLs printed by `azd`:

```bash
azd show
```

Keep the backend and frontend URLs for the smoke test. Do not publish the
resource group, Key Vault, registry, or internal service credentials.

## Post-deployment smoke test

Set shell variables locally, without committing them:

```bash
export BACKEND_URL="https://<backend-fqdn>"
export FRONTEND_URL="https://<frontend-fqdn>"
```

Check the backend:

```bash
curl --fail --show-error "$BACKEND_URL/health"
curl --fail --show-error "$BACKEND_URL/v1/matches/smoke/cards"
```

Check the frontend:

```bash
curl --fail --show-error "$FRONTEND_URL/" >/dev/null
curl --fail --show-error "$FRONTEND_URL/about" >/dev/null
curl --fail --show-error "$FRONTEND_URL/review" >/dev/null
```

In a real browser:

1. Open the frontend URL.
2. Confirm the page shows `Disconnected` only before starting a replay.
3. Select each of the four storylines.
4. Start a replay and confirm `Connected`, clock movement, score changes,
   event dots, cards, and momentum updates.
5. Confirm Swahili cards show an English gloss beneath the Swahili text.
6. Switch to English and French, then restart the replay.
7. Switch to Analyst mode and verify xG, possession, field tilt, pressure, and
   tempo metrics.
8. Toggle Audio-only mode and verify the reduced interface.
9. Open About and verify synthetic-data, attribution, and AI-disclosure text.
10. Open Review, authenticate with the reviewer key, and test one correction
    approval and one rejection.

For a configured Azure environment, also verify that a generated card has an
audio URL, that Content Safety failures do not stall the feed, and that the
fallback path still produces a card when the model is unavailable.

## Observability and operating limits

Before sharing the public URL:

- Confirm Application Insights receives card latency, audio latency, verifier,
  fallback, and quota metrics.
- Set an alert for repeated startup failures, 5xx responses, WebSocket
  disconnect spikes, and rate-limit spikes.
- Confirm Container Apps has at least one warm backend replica for the demo.
- Confirm the session cap and idle timeout prevent unbounded resource use.
- Confirm Cosmos and Blob retention policies are appropriate for synthetic
  demo data.
- Record the deployed image tags and the `azd` environment name.

## Rollback and teardown

Keep the previous known-good image tags. To deploy a previous version, set the
environment image tag values to those immutable tags and run:

```bash
azd deploy
```

Do not use `latest` for an emergency rollback when immutable tags are
available. To remove the environment after the judging period:

```bash
azd down
```

Review the deletion plan carefully before confirming; this removes the Azure
resources for the environment.

## Gaps to close before calling production ready

The 26 Oct 2026 demo deployment closed the live-integration gaps. Remaining
items are either operational hardening or human deliverables:

- **Verified live:** `/api/config` returns deployed backend/`wss://` URLs;
  Speech has both Swahili voices; all four Foundry deployments answer chat
  requests; a live Swahili session produced an `audio_update` and a public
  `audio/mpeg` blob; a real Chrome session rendered the commentary player and
  advanced playback; rotated reviewer key returns 200 and the old placeholder
  returns 401; `/mcp` returns 401 for missing/invalid Bearer tokens and serves
  authenticated tool calls for a valid `MCP_API_KEY`; Cosmos state snapshots
  are readable through `/v1/matches/{id}/state` and MCP snapshot fallback.
- **CORS / custom domain:** the template computes
  `MSIMULIZI_ALLOWED_ORIGINS` from the default frontend Container App domain.
  Adding a custom domain requires updating it plus `BACKEND_URL` and `WS_URL`.
- **Persistence and sessions:** match snapshots, key moments, narration cache,
  overlay cards, audit entries, and viewer corrections are written to Cosmos;
  the in-memory fake remains for offline tests. Active replay sessions and the
  WebSocket manager are still in-process, so keep the backend at one replica
  until a shared session/WebSocket backplane is added.
- **CI deployment gate:** the workflow deploys on every push to `main`. Add
  environment approval, staging promotion, or a protected production branch
  before using it for a public production environment.
- **Post-deploy verification:** `scripts/verify_azure_deployment.py` now makes
  real Speech and chat calls, but the CI step is still best-effort. Make it a
  release gate with endpoints supplied from the provisioned environment.
- **Frontend warnings:** the build passes, but remaining ESLint warnings in
  tests, the home page dependency list, and metric ARIA attributes should be
  cleaned up before a final accessibility review.
- **Capacity and cost:** load-test WebSockets, model calls, Speech, Cosmos, and
  Blob usage with the intended replica and rate-limit settings. The live demo
  has a USD 100/month budget (`msim-msimulizi-demo2-monthly`, defined in
  `infra/budget.bicep`) with 50/80/100% actual and 100% forecast alerts; adjust
  the amount after the load test if needed.
- **Public demo resilience:** test a full replay with model quota exhausted and
  confirm the bundle/fallback path remains grounded, translated, and visibly
  labelled.
- **Human deliverables:** native-speaker Swahili review, demo video, pitch, and
  submission remain open (tasks 33–34); hard deadline 27 Oct 2026 23:59 PT.

## Release record

### 27 Oct 2026 — audio, MCP auth, Cosmos persistence, budget

| Field | Value |
| --- | --- |
| `azd` environment | `msimulizi-demo2` |
| Region / resource group | `eastus2` / `rg-msimulizi-demo2` |
| Backend image | `msimmsimulizidemo2acrtt6h7mdhmoucs.azurecr.io/msimulizi/backend-msimulizi-demo2:azd-deploy-1793053582` |
| Frontend image | `msimmsimulizidemo2acrtt6h7mdhmoucs.azurecr.io/msimulizi/frontend-msimulizi-demo2:azd-deploy-1793052909` |
| Frontend URL | <https://msim-msimulizi-demo2-frontend.blackflower-72b7c0e4.eastus2.azurecontainerapps.io> |
| Backend URL | <https://msim-msimulizi-demo2-backend.blackflower-72b7c0e4.eastus2.azurecontainerapps.io> |
| WebSocket URL | `wss://msim-msimulizi-demo2-backend.blackflower-72b7c0e4.eastus2.azurecontainerapps.io/ws` |
| Cost budget | `msim-msimulizi-demo2-monthly`, USD 100/month, 50/80/100% actual + 100% forecast |
| Tests | 269 backend tests, 42 frontend tests, frontend build, Ruff lint, Bicep build, repo hygiene |
| Smoke test | 27 Oct 2026 UTC: health 200 with `cosmos: live` / `mcp: live`; MCP missing/invalid 401 and valid 200; Swahili card + English gloss; public MP3 200 `audio/mpeg`; Chrome normal-view playback advanced; Cosmos snapshot and MCP snapshot fallback verified |
| Rollback | Set the previous image on each Container App with `az containerapp update --image <previous-tag>`, then recheck `/health` |

The canonical session ID fix is included: `comeback_from_two_down` now resolves
to `comeback-from-two-down-42` everywhere (session response, events, cards,
Cosmos partitions, and MCP lookups).

### 26 Oct 2026 — demo deployment

| Field | Value |
| --- | --- |
| `azd` environment | `msimulizi-demo2` |
| Region / resource group | `eastus2` / `rg-msimulizi-demo2` |
| Backend image | `msimmsimulizidemo2acrtt6h7mdhmoucs.azurecr.io/msimulizi/backend-msimulizi-demo2:azd-deploy-1793050519` |
| Frontend image | `msimmsimulizidemo2acrtt6h7mdhmoucs.azurecr.io/msimulizi/frontend-msimulizi-demo2:azd-deploy-1793050822` |
| Frontend URL | <https://msim-msimulizi-demo2-frontend.blackflower-72b7c0e4.eastus2.azurecontainerapps.io> |
| Backend URL | <https://msim-msimulizi-demo2-backend.blackflower-72b7c0e4.eastus2.azurecontainerapps.io> |
| WebSocket URL | `wss://msim-msimulizi-demo2-backend.blackflower-72b7c0e4.eastus2.azurecontainerapps.io/ws` |
| Smoke test | 26 Oct 2026 UTC: health 200, `/api/config` runtime URLs correct, both Swahili voices present, four Foundry deployments answer, Swahili card + English gloss, public MP3 `200 audio/mpeg` |
| Rollback | Redeploy the previous image tag with `azd deploy --from-package <tag>` |

For each subsequent public release, record the same fields, the operator, and
the accepted gaps from the section above.
