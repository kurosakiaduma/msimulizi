# Azure resources and environment wiring

This is the pre-deployment checklist for the Msimulizi public demo. It covers
what `infra/main.bicep` creates, which values `azd` injects automatically, and
what still has to be set by hand before the demo is safe to expose.

The infrastructure has **not** been provisioned yet. Running `azd up` creates
billable resources; do that only after the preflight items below are checked.

---

## 1. What is already wired in code

| Area | State |
| --- | --- |
| Production audio (`renderer/audio`) | Integrated into `api/main.py` and `api/pipeline_runner.py`. Captions broadcast first; speech is synthesized in the background and sent as `audio_update`. |
| Speech authentication | Managed identity (`DefaultAzureCredential`). No Speech key is stored in the container app. |
| Audio storage | `AzureBlobStore` with managed identity; public-read `audio` container. |
| Foundry client | Migrated to the unversioned `/openai/v1/` API, with managed-identity token refresh. |
| Content Safety | Managed-identity client wired into the backend lifespan and verifier. |
| Frontend connection URLs | Runtime `/api/config` route; the container reads `BACKEND_URL` and `WS_URL` at request time, so one image works in every environment. |
| Container images | Backend and frontend Dockerfiles build successfully locally. |
| Model deployments | GA `gpt-5.4` / `gpt-5.4-mini` deployments; the old `gpt-4o` versions are deprecated for new subscriptions. |
| Tests | `261` backend tests and `39` frontend tests pass offline. |

---

## 2. Resources created by `infra/main.bicep`

`<env>` is `AZURE_ENV_NAME` (for example `prod`). All names are prefixed
`msim-<env>` unless noted.

| Resource | Name | SKU / scale | Why it exists |
| --- | --- | --- | --- |
| Resource group | `rg-<env>` (azd default) | — | Holds everything below |
| User-assigned managed identity | `msim-<env>-mid` | — | Pulls images and authenticates to Speech, Foundry, Content Safety, Storage, Key Vault, Cosmos |
| Container registry | `<prefix>acr<unique>` | Basic | Backend and frontend images |
| Log Analytics workspace | `msim-<env>-law` | PerGB2018, 30-day retention | Container logs |
| Application Insights | `msim-<env>-ai` | — | Requests, dependencies, traces |
| Key Vault | `msim-<env>-kv` | Standard, RBAC | MCP and reviewer keys |
| Cosmos DB account | `msim-<env>-cosmos` | Serverless **off**; 400 RU/s shared throughput | Match state, cards, cache, audit, corrections |
| Cosmos database | `msimulizi` | 400 RU/s | Contains `match_state_snapshots`, `key_moments`, `narration_cache`, `overlay_cards`, `audit_log`, `corrections` |
| Storage account | `msim<env>stor` (no hyphens) | Standard_LRS, Hot | Public-read audio blobs |
| Blob container | `audio` | Blob-level anonymous read | Speech MP3 playback |
| Azure AI Speech | `msim-<env>-speech` | S0 | Swahili/English/French TTS |
| Azure AI Content Safety | `msim-<env>-cs` | S0 | Verifier safety check |
| Microsoft Foundry account | `msim-<env>-foundry` | S0 | Azure OpenAI |
| Foundry deployments | `msimulizi-explainer`, `msimulizi-narrator-sw`, `msimulizi-narrator-en-fr`, `msimulizi-verifier` | GlobalStandard, capacity 10 each | Structured output, narration, verification |
| Container Apps environment | `msim-<env>-acaenv` | — | Hosts both apps |
| Backend Container App | `msim-<env>-backend` | 0.5 CPU / 1 Gi, **min 1 replica**, max 3 | FastAPI + WebSocket + MCP |
| Frontend Container App | `msim-<env>-frontend` | 0.25 CPU / 0.5 Gi, min 1, max 3 | Next.js viewer UI |

### Identity roles granted by the template

| Scope | Role |
| --- | --- |
| Container registry | `AcrPull` |
| Key Vault | `Key Vault Secrets User` |
| Storage account | `Storage Blob Data Contributor` |
| Speech account | `Cognitive Services Speech User` |
| Foundry account | `Cognitive Services OpenAI User` |
| Content Safety account | `Cognitive Services User` |
| Cosmos account | `Cosmos DB Built-in Data Contributor` |

Role assignments can take a few minutes to propagate. If the first backend
revision logs authorization failures, restart it before changing code.

---

## 3. Environment variables

### 3.1 Set automatically by Bicep

These are already in the backend Container App:

| Variable | Source |
| --- | --- |
| `AZURE_CLIENT_ID` | User-assigned managed identity |
| `KEY_VAULT_URL` | Key Vault URI |
| `COSMOS_ENDPOINT` | Cosmos account endpoint |
| `COSMOS_DATABASE` | `msimulizi` |
| `FOUNDRY_ENDPOINT` | Foundry account endpoint |
| `SPEECH_ENDPOINT` | Speech custom-domain endpoint |
| `CONTENT_SAFETY_ENDPOINT` | Content Safety endpoint |
| `STORAGE_ACCOUNT_URL` | Blob endpoint |
| `AUDIO_BLOB_ACCOUNT_URL` | Blob endpoint (audio alias) |
| `AUDIO_BLOB_CONTAINER` | `audio` |
| `SPEECH_USE_MANAGED_IDENTITY` | `true` |
| `APP_ENV` | `production` |
| `MSIMULIZI_ALLOWED_ORIGINS` | Frontend Container App URL |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | Application Insights secret |
| `MCP_API_KEY` | Key Vault secret `mcp-api-key` |
| `MSIMULIZI_REVIEWER_KEY` | Key Vault secret `reviewer-api-key` |
| `ENVIRONMENT_NAME` | `AZURE_ENV_NAME` |
| `FOUNDRY_REASONING_EFFORT` | `none` (keeps calls inside the 3-second budget) |

Frontend Container App:

| Variable | Source |
| --- | --- |
| `BACKEND_URL` | Backend public URL (read by `/api/config` at runtime) |
| `WS_URL` | `wss://<backend>/ws` (read by `/api/config` at runtime) |

### 3.2 Set before `azd up`

| Variable | Required? | Notes |
| --- | --- | --- |
| `AZURE_ENV_NAME` | Yes | Short lowercase name, e.g. `prod` or `demo`. Used in every resource name. |
| `AZURE_LOCATION` | Yes | Use `eastus` unless your subscription has model/voice limits elsewhere. Confirm both Foundry model and Swahili voice availability. |
| `AZURE_SUBSCRIPTION_ID` | Yes | Select the intended subscription; do not deploy into the wrong tenant. |
| `BACKEND_IMAGE_TAG` / `FRONTEND_IMAGE_TAG` | No | Default `latest`; set a git SHA for immutable revisions. |
| `FOUNDRY_MAX_COMPLETION_TOKENS` | No | Caps output size for latency/cost; unset uses the model default. |

`azd env new <name>` sets `AZURE_ENV_NAME`; then:

```bash
azd env set AZURE_LOCATION eastus
azd env set AZURE_SUBSCRIPTION_ID <subscription-id>
```

### 3.3 Local development only (never commit)

Copy `.env.example` to `.env` and set these only for local runs:

| Variable | Notes |
| --- | --- |
| `SPEECH_API_KEY` | Optional; omit to use your `az login` identity |
| `SPEECH_USE_MANAGED_IDENTITY` | `false` locally with a key, `true` with `az login` |
| `FOUNDRY_API_KEY` | Optional; omit to use `az login` |
| `CONTENT_SAFETY_API_KEY` | Optional; omit to use `az login` |
| `MCP_API_KEY` | Optional locally; MCP auth is disabled when unset |
| `MSIMULIZI_REVIEWER_KEY` | Needed for `/review` endpoints |

The back end starts with audio/LLM/safety disabled if their endpoints are
absent, so a missing local variable does not crash the API.

---

## 4. Preflight checks

### 4.1 Azure sign-in

`azd auth login` is done. The verification script and most operational
commands also need the Azure CLI:

```bash
az login
az account set --subscription <subscription-id>
az account show
```

### 4.2 Resource providers

```bash
for ns in Microsoft.App Microsoft.DocumentDB Microsoft.CognitiveServices \
          Microsoft.ContainerRegistry Microsoft.OperationalInsights \
          Microsoft.Insights Microsoft.KeyVault Microsoft.ManagedIdentity \
          Microsoft.Storage; do
  az provider register --namespace "$ns" --wait
done
```

### 4.3 Foundry access and quota

The template uses `gpt-5.4` and `gpt-5.4-mini` (GA). The previously pinned
`gpt-4o` / `gpt-4o-mini` versions are **deprecated for new subscriptions**;
a brand-new subscription cannot create those deployments even though their
retirement date is in 2027.

Confirm before provisioning:

```bash
# Models available in the chosen region (after selecting a subscription)
az cognitiveservices model list -l eastus -o table

# Current quota usage for the subscription/region
az cognitiveservices usage list -l eastus -o table
```

You need capacity for four deployments at `10` (thousand TPM each) in the
chosen region. If `gpt-5.4` is unavailable, change `config/foundry_models.yaml`
and the four `deployment*` resources in `infra/main.bicep` together.

Current retirement dates from the Foundry schedule (checked 26 Oct 2026):

| Model | Version | Lifecycle | Retires |
| --- | --- | --- | --- |
| `gpt-5.4` | `2026-03-05` | GA | 2027-09-02 |
| `gpt-5.4-mini` | `2026-03-17` | GA | 2027-09-21 |
| `gpt-4o` | `2024-08-06` | Deprecated (existing customers only) | 2027-04-14 |
| `gpt-4o-mini` | `2024-07-18` | Deprecated (existing customers only) | 2027-04-14 |

### 4.4 Speech voices

The default voices are:

| Language | Voice |
| --- | --- |
| Swahili (Kenya) | `sw-KE-ZuriNeural` |
| Swahili (Tanzania) | `sw-TZ-RehemaNeural` |
| English | `en-US-AriaNeural` |
| French | `fr-FR-DeniseNeural` |

`build_audio_service` verifies them against the live Speech catalogue at
startup. If the chosen region does not carry them, the API starts with audio
disabled rather than failing every card. After deployment run:

```bash
python scripts/verify_azure_deployment.py
```

If a voice is missing, set the overrides and redeploy (for example
`AUDIO_VOICE_SW=sw-KE-...`) or pick a region that carries the East African
voices.

### 4.5 Key Vault secrets

`infra/main.bicep` creates two **placeholder** secrets:

- `mcp-api-key`
- `reviewer-api-key`

Replace both before exposing the demo. A deterministic placeholder is public
in the repository and must never be used in production.

```bash
KV_URI=$(azd env get-value keyVaultUri)
KV_NAME=${KV_URI#https://}
KV_NAME=${KV_NAME%%.*}

MCP_KEY=$(openssl rand -hex 32)
REVIEWER_KEY=$(openssl rand -hex 32)

az keyvault secret set --vault-name "$KV_NAME" --name mcp-api-key --value "$MCP_KEY"
az keyvault secret set --vault-name "$KV_NAME" --name reviewer-api-key --value "$REVIEWER_KEY"

printf 'MCP_API_KEY=%s\nMSIMULIZI_REVIEWER_KEY=%s\n' "$MCP_KEY" "$REVIEWER_KEY" \
  > /tmp/opencode/msimulizi-keys.txt
chmod 600 /tmp/opencode/msimulizi-keys.txt
```

The Container App references the Key Vault secret by name. After rotating a
secret, create a new revision so the value is resolved again:

```bash
RG=$(azd env get-value AZURE_RESOURCE_GROUP 2>/dev/null || echo "rg-$(azd env get-value AZURE_ENV_NAME)")
az containerapp list -g "$RG" -o table
az containerapp update -g "$RG" -n msim-<env>-backend \
  --set-env-vars KEY_ROTATED_AT="$(date +%s)"
```

Or simply redeploy the backend with `azd deploy backend`.

Do not commit or paste `/tmp/opencode/msimulizi-keys.txt` into the repo.

### 4.6 Cost controls

The demo is free to viewers, but Azure resources are billable:
- Cosmos DB is provisioned at 400 RU/s and is always on.
- Both Container Apps keep at least one replica.
- ACR Basic and Log Analytics add a small fixed monthly charge.
- Speech and Foundry are pay-as-you-go.

Set a budget alert before leaving it public:

```bash
az consumption budget create \
  --budget-name msimulizi-demo \
  --amount 50 \
  --category cost \
  --time-grain monthly \
  --start-date "$(date -u +%Y-%m-01)" \
  --end-date 2026-12-31
```

Adjust the amount to the subscription's comfort level. `azd down` removes the
resource group and stops the spend.

---

## 5. Deploy sequence

```bash
# 1. Sign in
az login
azd auth login

# 2. Create the azd environment and select the subscription/location
azd env new msimulizi-demo
azd env set AZURE_LOCATION eastus
azd env set AZURE_SUBSCRIPTION_ID <subscription-id>

# 3. Provision, build, and deploy
azd up
```

`azd up` runs `provision` first, so the ACR output exists before `azd`
packages and pushes the images. The frontend Dockerfile uses the repository
root as its build context (`context: ../`), matching its `COPY frontend/...`
paths.

If a previous partial deployment exists, use:

```bash
azd provision
azd deploy
```

After the first successful deployment, set and rotate the Key Vault secrets
(section 4.5), restart the backend, then verify.

---

## 6. Post-deployment verification

```bash
export SPEECH_ENDPOINT=$(azd env get-value speechEndpoint)
export FOUNDRY_ENDPOINT=$(azd env get-value foundryEndpoint)
python scripts/verify_azure_deployment.py

curl -fsS "$(azd env get-value backendUrl)/health"
curl -fsS "$(azd env get-value frontendUrl)/api/config"
```

Expected:
- Voice check finds `sw-KE-ZuriNeural` and `sw-TZ-RehemaNeural`.
- All four deployments exist with the expected model/version and retirement
  dates after 10 Nov 2026.
- `/health` returns `{"ok":true,...}`.
- `/api/config` returns the backend and `wss://` URLs, not `localhost`.

Then open the frontend, start a replay, and confirm:
1. Captions appear immediately.
2. `audio_update` follows and the browser plays the MP3.
3. Switching Swahili/English/French selects the right voice.
4. MCP (`/mcp`) and reviewer endpoints reject requests without their keys.

```bash
# MCP should return 401/403 without the bearer token
curl -i "$(azd env get-value backendUrl)/mcp"

# Reviewer queue should reject a missing key
curl -i "$(azd env get-value backendUrl)/v1/corrections/queue"
```

---

## 7. Things that still need a human decision

1. **Foundry model availability/quota.** `gpt-5.4` and `gpt-5.4-mini` are the
   current GA choice, but quota and regional availability are
   subscription-specific. Confirm before `azd up`.
2. **Speech voice availability.** The startup check is strict by default. If
   East African voices are unavailable in the region, set the voice overrides
   or choose another region.
3. **Key Vault placeholder rotation.** Required before the public demo.
4. **Budget and teardown.** Decide the monthly cap and who runs `azd down`
   after 10 Nov 2026.
5. **Custom domains / CORS.** The template computes CORS from the default
   Container Apps domain. Adding a custom domain requires updating
   `MSIMULIZI_ALLOWED_ORIGINS`, `BACKEND_URL`, and `WS_URL`.
6. **Native-speaker Swahili review and demo video.** Tasks 15, 33, and 34 in
   `.kiro/specs/msimulizi/tasks.md` are still open and cannot be completed by
   code alone.

## 8. Known limitations of the current template

- No VNet/private endpoints. All services are public; the audio container is
  intentionally public-read.
- Cosmos DB uses a single region and no autoscale; 400 RU/s is enough for the
  demo but not for a large audience.
- The custom `audit_log` create-only Cosmos role is defined but the identity
  is also granted the broader Data Contributor role, so audit writes are not
  actually restricted yet.
- Container Apps scale-to-zero is disabled on purpose so in-memory sessions
  survive; this is a fixed cost even when nobody is watching.
- The backend image uses an editable install and the `pyproject.toml`
  dependency set, not `uv sync --frozen`; rebuilds can pick up newer allowed
  versions. Pin versions in `uv.lock`/`pyproject.toml` before a long-lived
  production deployment.

---

## 9. Feasibility assessment against the brief

**What is ready:** the feature set in `.kiro/specs/msimulizi/tasks.md` is
implemented (tasks 1–32) and covered by offline tests. The audio subsystem,
managed-identity authentication, runtime frontend configuration, and container
builds have been exercised locally; both images build and the backend starts
with bundle data when Azure is absent.

**What is not yet proven:** no Azure resource has been created, so live model
deployment, Speech voice availability, quota, managed-identity propagation, and
browser WebSocket/audio playback remain unverified. Those are operational
risks, not missing application code.

**What can still block the 10 Nov 2026 demo:** the submission deadlines (task
34) are the hard constraint. If model quota or Swahili voices are unavailable
in the chosen subscription/region, the bundle replay and caption path still
work, but the live LLM/TTS enhancement will fall back or be disabled. Resolve
the checks in sections 4.3 and 4.4 before claiming the demo is production-ready.

**Assessment:** the brief is technically realizable with this codebase. The
remaining work is Azure access/approval, secret rotation, one live smoke test,
and the human deliverables (native-speaker review and demo video) — not another
round of architectural changes.
