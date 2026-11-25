# User-configurable AI models

GeoFathom treats model selection as user-managed configuration, not a fixed
list of supported model names. Three editable presets ship with the platform:

| Preset ID | Runtime | Initial tag |
| --- | --- | --- |
| `local-saluki` | Ollama (local) | `saluki` |
| `cloud-groq` | GroqCloud API | `openai/gpt-oss-120b` |
| `cloud-gemini` | Google Gemini API | `gemini-3.8-flash` |

You may change all three presets and create up to 47 additional entries.
An entry can be disabled, and custom entries can be removed. Local Saluki
is the initial preference; this does not mean it is preinstalled.

## What users can configure

- Model display name and stable model ID
- Model identifier or the actual installed server tag
- Provider adapter: `ollama`, `groq`, `gemini`, `openai-compatible`
- Base URL for Ollama and OpenAI-compatible inference
- Server-side environment variable containing credentials
- Enabled state, selected model, and persisted default model

An OpenAI-compatible endpoint can point to a local llama.cpp, vLLM or
LM Studio server, or to a compatible hosted API. For providers with different
wire protocols, a new provider adapter must be added; specifying an arbitrary
URL is not enough to support every API protocol.

## Web configuration

1. Copy `.env.example` to `.env` in the repository root.
2. Set `GEOFATHOM_MODEL_ADMIN_TOKEN` to a long random secret.
3. Start FastAPI and the web workspace.
4. Under **Ask GeoFathom**, open the model settings icon.
5. Enter the administrator token for configuration changes.
6. Choose **Add model** or **Edit**. Set the provider, model tag, endpoint,
   and optional credential environment variable.
7. Save. Select the model in the model dropdown and click **Test API**.
8. Optionally choose **Set default** to persist the startup selection.

The administration token is held only in browser memory and is not persisted
in localStorage. If sharing a deployment with other users, add real user
authentication, rate limits and per-user catalogs before enabling access.

## Example: add a local model

Choose `ollama`, model ID `local-mistral`, name `Local Mistral`,
model tag `mistral:latest` (or the actual installed tag), and endpoint
`http://127.0.0.1:11434`. No API key is needed.

The API reports a model as configured when its runtime settings are present.
Only **Test API** confirms that the model server is reachable and returns
valid structured intent JSON.

## Example: add a custom cloud model

Add this variable to your local `.env` file:

```ini
GEOFATHOM_MODEL_KEY_MY_CLOUD=your-secret-api-key
```

Choose `openai-compatible`, set a model ID, a display name, the model tag,
the provider's HTTPS `/v1` base URL and the credential variable
`GEOFATHOM_MODEL_KEY_MY_CLOUD`. Restart FastAPI after changing `.env`.

Groq and Gemini have their own adapters with official API endpoints, so they
only require a valid model tag and the relevant provider API key variable.

Never paste an API key into the endpoint URL or model identifier. Secret
values are never included in the catalog JSON or read responses.

## Service endpoints

| Endpoint | Purpose |
| --- | --- |
| `GET /models/catalog` | List presets and user entries, without secrets |
| `PUT /models/catalog/{id}` | Add or modify an entry (admin token) |
| `DELETE /models/catalog/{id}` | Remove a custom entry (admin token) |
| `PUT /models/selection` | Persist the default model (admin token) |
| `POST /models/probe` | Test a specific model ID through a live request |
| `POST /assistant` | Use the requested `model_id` for a geographic task |

The write endpoints require the `X-GeoFathom-Admin-Token` header, whose
value must match `GEOFATHOM_MODEL_ADMIN_TOKEN` in the FastAPI environment.
If that variable is empty, all catalog writes are rejected.

Only HTTPS is accepted for remote OpenAI-compatible endpoints.
Unencrypted HTTP is permitted exclusively for loopback addresses. API
secrets are referenced through `GEOFATHOM_MODEL_KEY_*` environment
variables or the documented provider variables, not arbitrary process
variables. This is a local-first developer feature, not yet a hosted
multi-user credential-vault service.

## Storage and compatibility

User catalog changes persist to `data/model-catalog.json`, excluded from Git
through `.gitignore`. No user entry is silently substituted with a different
model when its credentials are missing. The user receives an explicit
unconfigured response and can choose another model.

Older `profile: "default" | "analysis"` requests remain supported for
existing integrations. New applications should submit `model_id` instead.
The provider adapter remains interchangeable, so upgrading a model only
requires changing its catalog entry.
