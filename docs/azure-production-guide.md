# Msimulizi Azure Production Guide

This guide covers a controlled production deployment of Msimulizi to Azure
Container Apps using Azure Developer CLI (`azd`). It is intentionally explicit
about the checks that must be completed before making the demo public.

## Deployment topology

`azd up` provisions and deploys:

- A backend Container App running FastAPI/Uvicorn.
- A frontend Container App running the Next.js production server.
- The Azure Container Apps environment and container registry.
- Cosmos DB, Blob Storage, Key Vault, Application Insights, Microsoft Foundry,
  Azure AI Speech, Azure AI Content Safety, and the managed identity defined in
  [`infra/main.bicep`](../infra/main.bicep).

The frontend is a browser application. Its `NEXT_PUBLIC_*` values are embedded
into the JavaScript bundle during `npm run build`; changing a Container App
runtime environment variable after the image is built does not change those
values in an already-built client bundle.

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
azd env set AZURE_LOCATION eastus
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

At minimum, verify these production concerns:

- `FOUNDRY_ENDPOINT` and the selected model deployment are available.
- `SPEECH_ENDPOINT` has the intended `sw-KE` or `sw-TZ` voice.
- `CONTENT_SAFETY_ENDPOINT` is configured for generated text moderation.
- `COSMOS_ENDPOINT` and `COSMOS_DATABASE` point to the production account.
- `STORAGE_ACCOUNT_URL` and `AUDIO_CONTAINER` are configured if audio is
  enabled.
- `APPLICATIONINSIGHTS_CONNECTION_STRING` is configured.
- `MSIMULIZI_REVIEWER_KEY` is a long, randomly generated secret.
- `MSIMULIZI_ALLOWED_ORIGINS` contains only the deployed frontend origin.
- Session, WebSocket, LLM, Speech, and per-IP rate limits are finite.

Do not expose reviewer, MCP, Foundry, Speech, Content Safety, Cosmos, or
Storage credentials as `NEXT_PUBLIC_*` variables.

## Frontend URL configuration

The browser needs all three values:

```text
NEXT_PUBLIC_BACKEND_URL=https://<backend-fqdn>
NEXT_PUBLIC_WS_URL=wss://<backend-fqdn>/ws
NEXT_PUBLIC_API_BASE=https://<backend-fqdn>
```

These values must be supplied while the frontend image is built. The current
frontend Dockerfile provides build arguments with local defaults, while the
current Bicep template injects only `NEXT_PUBLIC_BACKEND_URL` as a Container App
runtime variable. That runtime variable cannot repair a client bundle that was
already built with `localhost` or another default.

Before production deployment, choose one of these safe approaches:

1. Update the `azd`/CI image build to pass all three build arguments from the
   resolved backend FQDN, then run `azd up`.
2. Build and push the frontend image manually with the three arguments, set
   `FRONTEND_IMAGE_TAG` to that immutable tag, and deploy the Bicep template
   with that tag.

Never accept the Dockerfile defaults for a public deployment. After deployment,
inspect the built application in a browser and confirm that the browser
connects to the backend FQDN over `wss://`, not to `localhost`, the frontend
hostname, or an old environment.

## Provision and deploy

After the frontend build-argument wiring has been verified:

```bash
azd provision
azd deploy
```

Or, for a first deployment:

```bash
azd up
```

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

The following items are not fully proven by local tests and must be closed or
explicitly accepted:

- **Frontend image configuration:** pass
  `NEXT_PUBLIC_BACKEND_URL`, `NEXT_PUBLIC_WS_URL`, and `NEXT_PUBLIC_API_BASE`
  at image build time. The existing Bicep runtime variable is insufficient.
- **Live Azure integration:** local validation uses fallback narration because
  Foundry, Speech, and Content Safety endpoints are unset. Run one authenticated
  staging smoke test.
- **Review security policy:** confirm the reviewer key is stored in Key Vault,
  rotated, and never exposed in browser logs or URLs.
- **CORS:** replace local origins with the exact deployed frontend origin.
- **Audio delivery:** verify Blob permissions, URL expiry/access policy, and
  browser playback over HTTPS.
- **Persistence:** verify whether cards, audit entries, and corrections are
  intentionally in-memory or persisted to Cosmos in production.
- **CI deployment gate:** the workflow currently deploys on every push to
  `main`. Add environment approval, staging promotion, or a protected
  production branch before using it for a public production environment.
- **Post-deploy verification:** make voice/model verification fail when a
  required production dependency is missing; a best-effort check is not a
  release gate.
- **Frontend warnings:** the build passes, but remaining ESLint warnings in
  tests, the home page dependency list, and metric ARIA attributes should be
  cleaned up before a final accessibility review.
- **Capacity and cost:** load-test WebSockets, model calls, Speech, Cosmos, and
  Blob usage with the intended replica and rate-limit settings; configure
  Azure budgets and alerts.
- **Public demo resilience:** test a full replay with model quota exhausted and
  confirm the bundle/fallback path remains grounded, translated, and visibly
  labelled.

## Release record

For each public release, record:

- Git commit SHA and image tags.
- Azure subscription, region, and `azd` environment name.
- Frontend, backend, WebSocket, and review URLs.
- Model and Speech deployment names.
- Smoke-test date and operator.
- Known accepted gaps and rollback image tag.
