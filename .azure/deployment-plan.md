# Azure Deployment Plan

## Status

**Deployed and Verified**

Approved by the user in the parent planning session. This file is the source of truth for implementation, validation, deployment, verification, documentation, and publication staging.

## Goal

Build a public, production-oriented sample that demonstrates persistent cross-session agent memory on Azure App Service with:

- Python 3.13, FastAPI, and Microsoft Agent Framework.
- Short-term conversation history in Azure Managed Redis through a custom `HistoryProvider`.
- Durable, user-scoped semantic memory in Azure Cosmos DB for NoSQL vector search through a custom `ContextProvider`.
- Azure OpenAI chat and embedding deployments.
- Managed identity, least-privilege RBAC, Key Vault, Application Insights, and Log Analytics.
- A browser UI, deterministic local fake mode, automated tests, deployment smoke tests, architecture assets, and a Tech Community draft.

## Azure Context

| Setting | Approved value |
| --- | --- |
| Subscription | Demo Three Subscription (`7e574780-0f87-42e8-af8c-5e8cb7d3540a`) |
| Primary region | `eastus` |
| Region fallback | `eastus2`, then `westus3`, only after a real capacity error |
| Selected deployment region | `eastus2` |
| Resource group | azd-generated from environment name |
| Deployment method | Azure Developer CLI with Bicep |

The approved quota review found capacity for the planned App Service, Cosmos DB, Azure OpenAI deployments, and model TPM. Azure Managed Redis quota discovery is unsupported; deployment is the authoritative capacity check.

## Application Architecture

1. A public FastAPI web application runs on Azure App Service Linux Premium v4 (`P0v4`), one instance, always on.
2. The browser stores a bounded demo `user_id` and `session_id` in local storage. This is demonstrative identity only; production systems must use authenticated identity claims.
3. A custom Agent Framework history provider stores conversation messages under `session:{user_id}:{session_id}` in Azure Managed Redis with a configurable seven-day TTL.
4. A custom Agent Framework context provider embeds the current prompt, performs a partition-scoped Cosmos DB vector query for the same `user_id`, injects relevant durable memories, and records memory attribution.
5. The agent uses Azure OpenAI `gpt-5-mini` for responses and `text-embedding-3-small` with 1,536 dimensions for memory embeddings.
6. Durable memory records include `id`, `user_id`, `text`, `category`, source turn metadata, timestamps, embedding, and content hash. Writes deduplicate by content hash.
7. Explicit API and UI operations support chat, remember, recall, list, forget, and starting a new conversation while retaining the same user.
8. Application Insights and Log Analytics capture operational telemetry without logging memory text or secrets.

## Azure Resources

| Component | Azure resource/configuration |
| --- | --- |
| Web application | Azure App Service Linux, Python 3.13, `P0v4`, one instance, always on |
| Session history | Azure Managed Redis `Balanced_B0`, TLS, Entra authentication, access keys disabled |
| Durable memory | Azure Cosmos DB for NoSQL serverless, database plus vector-enabled container, partition key `/user_id`, `quantizedFlat` vector index, local auth disabled |
| Chat model | Azure OpenAI `gpt-5-mini`, version `2025-08-07`, `GlobalStandard`, 10K TPM |
| Embeddings | Azure OpenAI `text-embedding-3-small`, version `1`, `Standard`, 10K TPM, 1,536 dimensions |
| Secrets boundary | Standard Azure Key Vault with RBAC, soft delete, and purge protection |
| Identity | App Service system-assigned managed identity with least-privilege data-plane roles |
| Observability | Workspace-based Application Insights and Log Analytics |

Data services may retain public network endpoints for this POC, but must require TLS and Entra/RBAC with local keys disabled.

## Security and Reliability Requirements

- Use `ManagedIdentityCredential` explicitly in Azure and `AzureCliCredential` locally.
- Never permit cross-user memory reads; every durable query must include and bind `user_id`.
- Validate and bound user IDs, session IDs, message sizes, recall limits, and request bodies.
- Propagate dependency failures through explicit API errors; do not return success-shaped fallbacks.
- Use TLS-only service connections and disable local/key authentication for Azure OpenAI, Cosmos DB, and Redis where supported.
- Assign only required data-plane roles to the App Service managed identity.
- Do not place secrets in source, Bicep outputs, application settings, logs, or documentation.
- Keep the public sample endpoint unauthenticated only for demonstration and clearly document production authentication requirements.

## Implementation Work

1. Research the current Microsoft Agent Framework Python API and package versions from official Microsoft documentation and samples.
2. Implement typed configuration, credential selection, provider abstractions, Azure-backed stores, deterministic fake stores, and the Agent Framework integration.
3. Implement the FastAPI APIs and interactive browser UI.
4. Add unit and API tests for provider lifecycle behavior, isolation, deduplication, TTL, bounded recall, validation, and failure propagation.
5. Add `scripts/smoke_test.py` covering health, same-session history, remember, cross-session recall, list, forget, and post-forget absence.
6. Generate azd configuration and Bicep for all approved resources and RBAC assignments.
7. Run formatting, linting, typing, tests, and local fake-mode functional verification.
8. Change this plan to `Ready for Validation`, invoke `azure-validate`, then invoke `azure-deploy`.
9. Set an azd environment to the approved subscription and region, deploy, and run the smoke test against the real endpoint.
10. Create architecture source/export, README, blog Markdown/HTML, and stage the HTML as an Apps on Azure Tech Community draft using Save Draft only.
11. Commit all deliverables with required Copilot trailers, push the branch, open a pull request to `main`, and report results to the parent session.

## Research Record

- Microsoft Agent Framework packages are pinned to the current stable releases: `agent-framework-core==1.11.0` and `agent-framework-openai==1.10.1`.
- The canonical Python provider types are `HistoryProvider` and `ContextProvider`. Custom providers implement `get_messages`/`save_messages` or `before_run`/`after_run` with `AgentSession` and `SessionContext`.
- Agent Framework messages are persisted with `Message.to_dict()` and restored with `Message.from_dict()` so tool and attribution metadata survive.
- `OpenAIChatClient` is configured for Azure with an explicit asynchronous `AzureCliCredential` locally or `ManagedIdentityCredential` in App Service, local framework-managed history, and server-side response storage disabled.
- The Responses API uses its current `preview` moniker while the classic embeddings API is pinned separately to `2024-10-21`; the embeddings route returns 404 when incorrectly given the Responses `preview` moniker.
- The Redis integration uses the current `redis-entraid==1.2.1` package. App Service uses its explicit system-assigned managed identity provider; local real-Azure development uses an explicit Azure CLI token provider. Local fake mode requires no Azure account.
- Azure Cosmos DB vector search uses `EnableNoSQLVectorSearch`, a new container with a 1,536-dimension `float32` cosine embedding policy, a `quantizedFlat` index, and the embedding path excluded from the regular index.
- The current Azure Verified Module `br/public:avm/res/cache/redis-enterprise:0.5.1` deploys Azure Managed Redis with the 2025-07-01 API, `Balanced_B0`, TLS, an Entra access-policy assignment, and access-key authentication disabled.
- Azure App Service FastAPI requires an explicit startup command. The deployment uses Python 3.13 as approved, Oryx dependency installation, and the required `azd-service-name` tag.
- Application Insights uses the Azure Monitor OpenTelemetry distribution and its connection string from the linked workspace-based resource.

## Validation Gates

- `ruff format --check`
- `ruff check`
- `mypy`
- `pytest`
- Local fake-mode browser/API verification
- `azd`/Bicep validation through the `azure-validate` workflow
- Real deployment through the `azure-deploy` workflow
- Deployed smoke test succeeds for the complete memory lifecycle
- Diagram PNG renders cleanly
- Tech Community HTML contains no raw HTTP request blocks or secrets

### Azure Validate Steps

- [x] AZD installation
- [x] `azure.yaml` schema validation
- [x] AZD environment setup
- [x] Authentication check
- [x] Subscription and location check
- [x] Aspire pre-provisioning checks — not applicable
- [x] Provision preview
- [x] Application and Bicep build verification
- [x] Docker build-context validation — not applicable
- [x] Package validation
- [x] Azure Policy validation
- [x] Aspire post-provisioning checks — not applicable
- [x] Static role assignment verification

## Generated Artifacts

- Application: `app/`, `pyproject.toml`, `requirements.txt`, `uv.lock`
- Browser UI: `app/static/`
- Tests: `tests/`
- Deployment smoke test: `scripts/smoke_test.py`
- Azure Developer CLI: `azure.yaml`, `.webappignore`
- Infrastructure: `infra/main.bicep`, `infra/resources.bicep`, `infra/main.parameters.json`

## Functional Verification

- Status: Verified
- Backend: The complete fake-mode API lifecycle passes, including health, same-session history, automatic and explicit memory, cross-session recall, list, forget, isolation, deduplication, TTL, history bounds, validation bounds, and dependency failure propagation.
- UI: Verified in a browser with no current console errors. A durable memory created in the UI was recalled in a newly generated conversation for the same demo user with visible attribution.
- Quality: Ruff formatting and linting pass, mypy strict typing passes, and all 10 pytest tests pass.
- Infrastructure: Bicep compiles successfully. The only compiler warning is missing local type metadata for the current `Microsoft.Cache/redisEnterprise@2025-07-01` resource used inside the pinned official Azure Verified Module.

## Configured AZD Environment

- Environment: `agent-memory`
- Subscription: Demo Three Subscription (`7e574780-0f87-42e8-af8c-5e8cb7d3540a`)
- Location: `eastus2`

## Role Assignment Verification

- Status: Verified
- Identity: App Service system-assigned managed identity
- Azure OpenAI: resource-scoped `Cognitive Services OpenAI User`
- Cosmos DB: account-scoped native `Cosmos DB Built-in Data Contributor`
- Key Vault: vault-scoped `Key Vault Secrets User`
- Azure Managed Redis: database-scoped Entra access-policy assignment with access keys disabled
- Generic subscription, resource-group, Owner, Contributor, and Reader roles are not assigned to the application.

## Section 7: Validation Proof

Validation completed at `2026-07-15T15:02:34Z`.

| Check | Command/tool | Result |
| --- | --- | --- |
| AZD installed | `azd version` | `1.23.14`, successful |
| AZD authentication | `azd auth login --check-status` | Logged in as `jordanselig@microsoft.com` |
| Environment | `azd env get-values` | `agent-memory`, approved subscription, `eastus2` |
| Schema | Azure Developer CLI `validate_azure_yaml` | Valid against stable schema |
| Python quality | `ruff format --check`, `ruff check`, `mypy`, `pytest` | Passed; 10 tests |
| Bicep build | `az bicep build --file infra/main.bicep --stdout` | Passed |
| Provision preview | `azd provision --preview --no-prompt` | Passed in `eastus2`; 11 top-level resources planned |
| Package | `azd package --no-prompt` | App Service deployment package created |
| Policy | Azure Policy assignment review plus definition inspection | Public access is audited; deny policies explicitly permit `P0v4`/`PremiumV4` |
| Roles | Static Bicep review | Required resource-scoped data-plane access present |

## Deployment Verification

- Completed: `2026-07-15T15:58:01Z`
- Resource group: `rg-agent-memory`
- Endpoint: `https://web-agent-memory-m4ryqjohhhc5k.azurewebsites.net/`
- `azd provision --no-prompt`: Passed
- `azd deploy --no-prompt`: Passed
- Health: HTTP 200 with `{"status":"ok","mode":"azure"}`
- Browser: Deployed UI loaded successfully with no console errors
- Smoke test: `SMOKE_OK`; verified same-session Redis history, explicit remember, new-session Cosmos recall for the same user, list, forget, and absence after forget

### Live Role Verification

- App Service managed identity: `0fd590da-c006-40cd-bb13-e74754460034`
- Azure OpenAI: `Cognitive Services OpenAI User` at the account scope
- Cosmos DB: native built-in data contributor role at the account scope
- Key Vault: `Key Vault Secrets User` at the vault scope
- Azure Managed Redis: `default` Entra policy assignment on the `default` database, provisioning state `Succeeded`
- Status: Pass

### Live Security Verification

- Azure OpenAI local authentication: disabled
- Cosmos DB local authentication: disabled
- Azure Managed Redis access-key authentication: disabled
- Azure Managed Redis client protocol: encrypted on port 10000
- Key Vault purge protection: enabled
- App Service plan: `P0v4`

### Deployment Corrections

- Serialized the two Azure OpenAI model deployments after ARM returned a parent-resource `RequestConflict` during concurrent creation.
- Added the explicit `aiohttp` runtime dependency required by asynchronous `ManagedIdentityCredential`.
- Split the Azure OpenAI API versions: Responses uses `preview`; embeddings uses `2024-10-21`. The classic embeddings route returns 404 with the Responses `preview` moniker.
- Added App Service-specific packaging exclusions, an Azure-mode smoke assertion, ref-counted conversation-lock cleanup, and a bounded global public-demo API throttle after publication review.

## Publication Verification

- Architecture source: `docs/architecture/architecture.excalidraw`
- Architecture PNG: `docs/architecture/architecture.png` (`2560x1654`)
- Blog sources: `blog/techcommunity.md` and WAF-safe `blog/techcommunity.html`
- Tech Community destination: Apps on Azure Blog
- Tech Community state: Saved as draft; not published and not submitted for review
- Draft editor: `https://techcommunity.microsoft.com/blog/AppsonAzureBlog/give-your-ai-agent-two-memories-with-azure-app-service/4537400/edit`

## Expected Outputs

- Application source and static UI
- Tests and deployed smoke test
- `azure.yaml` and `infra/` Bicep
- `.azure/deployment-plan.md`
- `docs/architecture/architecture.excalidraw`
- `docs/architecture/architecture.png`
- Full `README.md`
- `blog/techcommunity.md`
- `blog/techcommunity.html`
- Azure deployment URL and resource group
- Saved Tech Community draft URL, or an exact authentication blocker
- Git commit, pushed branch, and pull request

## Deviations

- Azure Managed Redis preflight returned `Creation of Azure Managed Redis is not supported for your subscription in East US`. Per the approved fallback order, capacity/model checks were rerun and the deployment location was changed to `eastus2`, where the full ARM what-if succeeded.
