# Azure resources and environment wiring

This is the deployment inventory for the Msimulizi public demo. It records what
is actually running, which values `azd` injects, which secrets have been
rotated, and what still has to happen before the demo is treated as production
ready.

> **Live deployment snapshot — 27 Oct 2026**
>
> | Item | Value |
> | --- | --- |
> | `azd` environment | `msimulizi-demo2` |
> | Resource group | `rg-msimulizi-demo2` |
> | Region | `eastus2` |
> | Frontend | <https://msim-msimulizi-demo2-frontend.blackflower-72b7c0e4.eastus2.azurecontainerapps.io> |
> | Backend | <https://msim-msimulizi-demo2-backend.blackflower-72b7c0e4.eastus2.azurecontainerapps.io> |
> | WebSocket | `wss://msim-msimulizi-demo2-backend.blackflower-72b7c0e4.eastus2.azurecontainerapps.io/ws` |
> | Backend image | `msimmsimulizidemo2acrtt6h7mdhmoucs.azurecr.io/msimulizi/backend-msimulizi-demo2:azd-deploy-1793054810` |
> | Frontend image | `msimmsimulizidemo2acrtt6h7mdhmoucs.azurecr.io/msimulizi/frontend-msimulizi-demo2:azd-deploy-1793052909` |
> | Cost budget | `msim-msimulizi-demo2-monthly` — USD 100/month, 50/80/100% actual + 100% forecast alerts |
> | Git commit deployed | `1c2a727` (`main` HEAD at deployment) |
>
> The first attempt in `eastus` failed because Cosmos DB reported regional
> capacity exhaustion. That resource group was deleted; the clean deployment is
> in `eastus2`. No resources remain in the old region.

---

## 1. What is running

`<env>` below is `msimulizi-demo2`; every name is the actual deployed name.

| Resource | Actual name | SKU / scale | Purpose |
| --- | --- | --- | --- |
| Resource group | `rg-msimulizi-demo2` | — | Holds the whole demo |
| User-assigned managed identity | `msim-msimulizi-demo2-mid` | — | ACR pull and data-plane auth |
| Container registry | `msimmsimulizidemo2acrtt6h7mdhmoucs` | Basic | Backend and frontend images |
| Log Analytics | `msim-msimulizi-demo2-law` | PerGB2018, 30 days | Container logs |
| Application Insights | `msim-msimulizi-demo2-ai` | — | Requests, dependencies, traces |
| Key Vault | `msim-msimulizi-demo2-kv` | Standard, RBAC | MCP and reviewer keys |
| Cosmos DB | `msim-msimulizi-demo2-cosmos` | 400 RU/s shared, single region | Match state, cards, cache, audit, corrections |
| Cosmos DB database | `msimulizi` | 400 RU/s | Six containers listed in `infra/main.bicep` |
| Storage account | `msimmsimulizidemo2stor` | Standard_LRS, Hot | Audio blobs |
| Blob container | `audio` | Anonymous blob read | Public MP3 playback |
| Azure AI Speech | `msim-msimulizi-demo2-speech` | S0 | Swahili/English/French TTS |
| Azure AI Content Safety | `msim-msimulizi-demo2-cs` | S0 | Verifier safety check |
| Microsoft Foundry | `msim-msimulizi-demo2-foundry` | S0 | Azure OpenAI |
| Foundry deployments | `msimulizi-explainer`, `msimulizi-narrator-sw`, `msimulizi-narrator-en-fr`, `msimulizi-verifier` | GlobalStandard, capacity 10 each | Structured output, narration, verification |
| Container Apps environment | `msim-msimulizi-demo2-acaenv` | — | Hosts both apps |
| Backend Container App | `msim-msimulizi-demo2-backend` | 0.5 CPU / 1 Gi, **min 1**, max 3 | FastAPI + WebSocket |
| Frontend Container App | `msim-msimulizi-demo2-frontend` | 0.25 CPU / 0.5 Gi, min 1, max 3 | Next.js viewer UI |
| Cost budget | `msim-msimulizi-demo2-monthly` | USD 100/month | Cost alerting at 50/80/100% actual and 100% forecast |

### Identity roles granted by `infra/main.bicep`

| Scope | Role |
| --- | --- |
| Container registry | `AcrPull` |
| Key Vault | `Key Vault Secrets User` |
| Storage account | `Storage Blob Data Contributor` |
| Speech account | `Cognitive Services Speech User` |
| Foundry account | `Cognitive Services OpenAI User` |
| Content Safety account | `Cognitive Services User` |
| Cosmos account | `Cosmos DB Built-in Data Contributor` |

The operator account also has `Key Vault Secrets Officer` on the demo vault,
plus `Cognitive Services Speech User` and `Cognitive Services OpenAI User`, to
run the post-deploy verifier locally. These operator grants are not in Bicep;
use an Entra group if the demo becomes a shared production environment.

---

## 2. Environment variables

### 2.1 Injected into the backend Container App

| Variable | Source / value |
| --- | --- |
| `AZURE_CLIENT_ID` | Managed identity client ID |
| `KEY_VAULT_URL` | Key Vault URI |
| `COSMOS_ENDPOINT` | Cosmos account endpoint |
| `COSMOS_DATABASE` | `msimulizi` |
| `FOUNDRY_ENDPOINT` | Foundry endpoint (client uses `/openai/v1/`) |
| `SPEECH_ENDPOINT` | Speech custom-domain endpoint |
| `CONTENT_SAFETY_ENDPOINT` | Content Safety endpoint |
| `STORAGE_ACCOUNT_URL` | Blob endpoint |
| `AUDIO_BLOB_ACCOUNT_URL` | Same Blob endpoint; audio alias |
| `AUDIO_BLOB_CONTAINER` | `audio` |
| `SPEECH_USE_MANAGED_IDENTITY` | `true` |
| `APP_ENV` | `production` |
| `MSIMULIZI_ALLOWED_ORIGINS` | Deployed frontend origin |
| `APPLICATIONINSIGHTS_CONNECTION_STRING` | App Insights secret |
| `MCP_API_KEY` | Key Vault secret `mcp-api-key` |
| `MSIMULIZI_REVIEWER_KEY` | Key Vault secret `reviewer-api-key` |
| `ENVIRONMENT_NAME` | `msimulizi-demo2` |
| `FOUNDRY_REASONING_EFFORT` | `none` — keeps chat calls inside the 3 s budget |

The following code defaults are used unless overridden: `MSIMULIZI_MAX_SESSIONS=8`,
`MSIMULIZI_SESSION_IDLE_SECONDS=600`, `MSIMULIZI_PER_IP_RATE_LIMIT=120`,
`AUDIO_VERIFY_VOICES=true`, `AUDIO_STRICT_VOICE_CHECK=true`, and the four voice
names in `renderer/audio/config.py`.

### 2.2 Injected into the frontend Container App

| Variable | Source |
| --- | --- |
| `BACKEND_URL` | Backend public URL |
| `WS_URL` | `wss://<backend>/ws` |

The browser does **not** bake these in at build time. `/api/config` reads the
server-side values at request time. `NEXT_PUBLIC_BACKEND_URL` and
`NEXT_PUBLIC_WS_URL` are local-development fallbacks only.

### 2.3 `azd` / deployment-time values

| Variable | Current value / note |
| --- | --- |
| `AZURE_ENV_NAME` | `msimulizi-demo2` |
| `AZURE_LOCATION` | `eastus2` |
| `AZURE_SUBSCRIPTION_ID` | Set in the `azd` environment; not committed |
| `KEY_MODE` | `preserve` after secret rotation; `bootstrap` on a fresh environment |
| `SERVICE_BACKEND_IMAGE_NAME` | Managed by `azd deploy` |
| `SERVICE_FRONTEND_IMAGE_NAME` | Managed by `azd deploy` |

`BACKEND_IMAGE_TAG` and `FRONTEND_IMAGE_TAG` were removed from the Bicep
parameters. Images are now selected by `azd deploy`, not by a template tag.

### 2.4 Local development only — never commit

| Variable | Note |
| --- | --- |
| `SPEECH_API_KEY` | Optional; omit to use your `az login` identity |
| `SPEECH_USE_MANAGED_IDENTITY` | `false` with a key, `true` with `az login` |
| `FOUNDRY_API_KEY` | Optional; omit to use `az login` |
| `CONTENT_SAFETY_API_KEY` | Optional; omit to use `az login` |
| `MCP_API_KEY` | Optional locally; `/mcp` allows all requests when unset, and requires a Bearer token whenever it is set |
| `MSIMULIZI_REVIEWER_KEY` | Needed for `/review` and correction endpoints |

The backend starts with audio/LLM/safety disabled when their endpoints are
absent, so local startup does not require Azure.

---

## 3. Secrets and rotation

`infra/main.bicep` creates two placeholder secrets **only** when
`KEY_MODE=bootstrap`:

- `mcp-api-key`
- `reviewer-api-key`

Both were rotated in the live vault on **26 Oct 2026 at 21:17 UTC**. The
values are not in the repository and should be stored in a team password
manager. After rotation, the backend was redeployed so Container Apps resolved
the new Key Vault values. Verification:

```text
new reviewer key  -> HTTP 200 on /v1/corrections/queue
old placeholder   -> HTTP 401
missing key       -> HTTP 401
```

`azd env set KEY_MODE preserve` is set on `msimulizi-demo2`, so a later
`azd up` will not overwrite the rotated values. On a fresh environment, leave
`KEY_MODE` unset (`bootstrap`), deploy once, rotate, then set `preserve`.

To rotate again:

```bash
KV_NAME=msim-msimulizi-demo2-kv
az keyvault secret set --vault-name "$KV_NAME" --name mcp-api-key --value "$(openssl rand -hex 32)"
az keyvault secret set --vault-name "$KV_NAME" --name reviewer-api-key --value "$(openssl rand -hex 32)"

# Force a new backend revision so Container Apps re-reads the Key Vault refs
az containerapp update -g rg-msimulizi-demo2 -n msim-msimulizi-demo2-backend \
  --set-env-vars KEY_ROTATED_AT="$(date +%s)"
```

The live `/mcp` mount now runs the full `mcp_server/server.py` implementation.
`BearerAuthMiddleware` validates `MCP_API_KEY` at the HTTP boundary before any
MCP protocol handling, and the per-tool check remains as defence in depth.
Verified on 27 Oct 2026:

```text
no Authorization header       -> HTTP 401
Authorization: Bearer wrong   -> HTTP 401
Authorization: Bearer <key>   -> HTTP 200; initialize, tools/list, tools/call all work
```

The registered tools are `get_match_state`, `list_key_moments`, and
`get_player_stats`. `MCP_ALLOWED_HOSTS` / `MCP_ALLOWED_ORIGINS` can be set to
opt into MCP SDK DNS-rebinding checks; the default mount relies on Bearer auth
because the Container Apps hostname is assigned after provisioning.

---

## 4. Deploying or updating

### 4.1 Fresh environment

```bash
az login
azd auth login

azd env new <env>
azd env set AZURE_SUBSCRIPTION_ID <subscription-id>
azd env set AZURE_LOCATION eastus2

azd up
```

`azd up` creates the apps with a temporary public bootstrap image, then builds
and pushes the real images and creates new revisions. This is deliberate: a
first provision cannot pull an image from an ACR that is still empty. Running
`azd provision` alone resets both apps to the bootstrap image; always follow it
with `azd deploy` (or use `azd up`).

After the first successful deployment:

```bash
# Rotate the two Key Vault secrets (section 3), then:
azd env set KEY_MODE preserve
```

### 4.2 Updating code only

```bash
azd deploy backend
azd deploy frontend
# or: azd up
```

`azd up` is safe after `KEY_MODE=preserve`: it will not reset the rotated
secrets.

### 4.3 Region notes

`eastus2` was chosen after `eastus` returned a Cosmos DB capacity error on
26 Oct 2026. Before choosing a different region for a fresh deployment,
verify all three:

```bash
az cognitiveservices model list -l <region> --query "[?model.name=='gpt-5.4'].model" -o table
az cognitiveservices usage list -l <region> --query "[?contains(name.value,'gpt-5.4')]" -o table
# Then after deployment, the verifier checks the Swahili voices live.
```

The Foundry deployments use `gpt-5.4` (`2026-03-05`, retires 2027-09-02) and
`gpt-5.4-mini` (`2026-03-17`, retires 2027-09-21), all after the 10 Nov 2026
demo window. The deprecated `gpt-4o` / `gpt-4o-mini` deployments are not used;
new subscriptions cannot create them.

---

## 5. Post-deployment verification

```bash
export SPEECH_ENDPOINT=https://msim-msimulizi-demo2-speech.cognitiveservices.azure.com/
export FOUNDRY_ENDPOINT=https://msim-msimulizi-demo2-foundry.openai.azure.com/
.venv/bin/python scripts/verify_azure_deployment.py
```

The script now:

- calls `<speech-endpoint>/tts/cognitiveservices/voices/list` and checks
  `sw-KE-ZuriNeural` and `sw-TZ-RehemaNeural`;
- sends a tiny chat request to each Foundry deployment and checks the model
  version returned by the service, not just the ARM deployment metadata.

Actual result on 26 Oct 2026:

```text
✓ Voice available: sw-KE-ZuriNeural
✓ Voice available: sw-TZ-RehemaNeural
✓ msimulizi-explainer      gpt-5.4-mini:2026-03-17
✓ msimulizi-narrator-sw    gpt-5.4:2026-03-05
✓ msimulizi-narrator-en-fr gpt-5.4-mini:2026-03-17
✓ msimulizi-verifier       gpt-5.4-mini:2026-03-17
✓ All deployment checks passed.
```

Other smoke checks:

```bash
BACKEND=https://msim-msimulizi-demo2-backend.blackflower-72b7c0e4.eastus2.azurecontainerapps.io
FRONTEND=https://msim-msimulizi-demo2-frontend.blackflower-72b7c0e4.eastus2.azurecontainerapps.io

curl -fsS "$BACKEND/health"
curl -fsS "$FRONTEND/api/config"
```

The live WebSocket smoke test created a Swahili replay and received:

```text
CARD 1   Goli! Juma Mwakazi anafunga dakika ya 12.
  gloss_en: Goal! Juma Mwakazi scores at minute 12.
AUDIO_UPDATE  https://msimmsimulizidemo2stor.blob.core.windows.net/audio/....mp3
AUDIO_FETCH   200 audio/mpeg  53,424 bytes  duration 8,904 ms
```

A real Chrome run against the public frontend then confirmed the normal viewer
mode renders the commentary player and advances playback:

```text
audio currentSrc  .../audio/....mp3
paused            false
currentTime       0.52 s
duration          6.50 s
readyState        4
error             null
```

The player is visible under the momentum bar even when the card itself is
retired, and a manual "Play commentary" button appears if the browser blocks
autoplay. Cosmos-backed verification after the same replay:

```text
GET /v1/matches/comeback-from-two-down-42/state  -> snapshot present
MCP get_match_state(match_id, no session)        -> source = "snapshot"
```

The first frontend request after a new revision can take longer than the 60 s
smoke-test timeout while Next.js starts; a retry returned HTTP 200. This is a
cold-start characteristic of the frontend, not a backend failure.

---

## 6. Cost and operating controls

The demo is free to viewers, but Azure resources are billable:

- Cosmos DB is fixed at 400 RU/s and is always on.
- Both Container Apps keep at least one replica; scale-to-zero is deliberately
  off so in-memory sessions survive.
- ACR Basic and Log Analytics add a small fixed monthly charge.
- Speech, Foundry, and Content Safety are pay-as-you-go.
- The public-read `audio` container has no lifecycle deletion policy yet.

**Budget alert created on 27 Oct 2026:**

```text
name        msim-msimulizi-demo2-monthly
scope       rg-msimulizi-demo2
amount      USD 100 / month
alerts      50% actual, 80% actual, 100% actual, 100% forecast
recipients  lukoritomelvin@gmail.com + subscription Owners
```

It is codified in [`infra/budget.bicep`](../infra/budget.bicep) and can be
redeployed or adjusted without touching the application stack:

```bash
az deployment group create \
  -g rg-msimulizi-demo2 \
  -f infra/budget.bicep \
  -p budgetName=msim-msimulizi-demo2-monthly \
     amount=100 \
     contactEmails='["operator@example.com"]'
```

`azd down` removes the resource group and stops the spend; delete the budget
first if you want to keep the subscription clean.

---

## 7. Remaining production gaps

1. **Custom domain and CORS:** the template uses the default Container Apps
   domain. Adding a custom domain requires updating `MSIMULIZI_ALLOWED_ORIGINS`,
   `BACKEND_URL`, and `WS_URL`.
2. **MCP/reviewer key distribution:** both secrets are rotated, but the team
   still needs a safe handoff path (password manager or Key Vault access) for
   the reviewer key.
3. **Teardown ownership:** decide who runs `azd down` after 10 Nov 2026 and
   removes the cost budget.
4. **Cross-replica sessions:** Cosmos persistence is wired, but active replay
   sessions and the WebSocket manager are still in-process. Keep the backend at
   one replica, or add a shared WebSocket backplane/session router, before
   scaling beyond one. `maxReplicas` is 3 today.
5. **CI deployment gate:** `.github/workflows/ci.yml` still deploys on every
   push to `main`. Add environment approval or a protected production branch.
   The verifier is currently best-effort in CI; make it a release gate with
   endpoints supplied from the environment.
6. **Capacity/load:** no load test has covered WebSockets, Speech concurrency,
   Foundry rate limits, or Blob egress at the intended audience size.
7. **Accessibility cleanup:** five pre-existing frontend lint warnings remain
   (tests, home-page dependencies, metric ARIA attributes).
8. **Native-speaker review, video, pitch, and submission:** tasks 33–34 remain
   human deliverables. The hard deadline is 27 Oct 2026 23:59 PT.

---

## 8. Feasibility assessment against the brief

**Ready:** the feature set through task 32 is implemented and covered by offline
tests. The production audio path, managed-identity auth, runtime frontend
configuration, and container builds have now been exercised against live Azure:
Speech voices exist, all four Foundry deployments answer, a replay produced a
public MP3, Chrome advanced playback in the normal viewer, MCP rejects
missing/invalid keys and serves authenticated tools, Cosmos persists match
snapshots/moments/cards/audit/corrections, and reviewer auth rejects the old
placeholder.

**Not yet proven:** load behavior, cross-replica session routing,
custom-domain/TLS setup, and the human quality review. These are operational or
review gaps, not missing application code.

**What can still block the demo:** the submission deadline is the hard
constraint. If model quota or Swahili voices become unavailable, the bundle and
caption path still works, but live LLM/TTS enhancement falls back or disables
audio. The current `eastus2` deployment passes both checks.

**Assessment:** the brief is technically realizable with this codebase. The
remaining work is production hardening, secret handoff, one final browser smoke
test, and the native-speaker/video/submission tasks — not another round of
architectural changes.
