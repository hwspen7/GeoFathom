# Model providers and free API testing

GeoFathom includes a user-managed model catalog. The three presets (local
Saluki 27B, Groq GPT-OSS 120B and Gemini 3.8 Flash) are editable examples,
not a fixed set. The legacy two-profile API remains for compatibility but
the web UI selects models by their persistent model IDs. New local and cloud
models can be added through the web model manager. See
[Model configuration](MODEL_CONFIGURATION.md). The language model interprets and plans a limited set of geographic
actions. It does not provide authoritative geospatial coordinates or areas.

## Cloud preset: GPT-OSS 120B via GroqCloud

- Provider key: `groq`
- Model ID: `openai/gpt-oss-120b`
- Endpoint: `https://api.groq.com/openai/v1/chat/completions`
- Key: `GEOFATHOM_GROQ_API_KEY` (or `GROQ_API_KEY`)
- Purpose: natural-language interpretation and geospatial tool dispatch

Official Groq free plan limits depend on the account. The November 2026
published base table lists 30 requests/minute, 1,000 requests/day and
200,000 tokens/day for GPT-OSS 120B. These are rate limits, not a promise of
unrestricted use. View current limits in GroqCloud.

Sources:
- https://console.groq.com/docs/rate-limits
- https://console.groq.com/docs/tool-use/overview
- https://console.groq.com/docs/openai

## Cloud preset: Gemini 3.8 Flash via Google AI Studio

- Provider key: `gemini`
- Model ID: `gemini-3.8-flash`
- OpenAI-compatible endpoint:
  `https://generativelanguage.googleapis.com/v1beta/openai/chat/completions`
- Key: `GEOFATHOM_GEMINI_API_KEY` (or `GEMINI_API_KEY`)
- Purpose: second tool-planning candidate and future multimodal analysis

Google currently lists free-of-charge standard input and output for Gemini 3.8
Flash on its free tier. Quotas vary by project and can change. The free tier
can use content to improve Google's products according to its pricing terms.
Do not send confidential project data without first reviewing this policy.

Source: https://ai.google.dev/gemini-api/docs/pricing

Gemini's image understanding is not a pixel-accurate, geographically referenced
segmentation engine. Reliable satellite tracing still requires licensed imagery
and a dedicated CV and GIS pipeline.

## Local preset: Saluki 27B and other Ollama models

If free-cloud quotas are exhausted or remote inference is inappropriate,
configure your own Ollama or OpenAI-compatible local server.
Saluki 27B is the initial selected model, but users may choose any other
compatible local or cloud model and persist that preference.
No weights or inference servers are installed by this repository.

Example:

    GEOFATHOM_LLM_PROVIDER=ollama
    GEOFATHOM_LLM_MODEL=<actual Ollama tag>
    GEOFATHOM_OLLAMA_URL=http://localhost:11434

The RTX 4070 Ti SUPER 16 GB is adequate for the development workstation and
many optimized vision workloads, but memory requirements for a particular
vision model depend on resolution, batch size, model checkpoint and precision.

## Live testing

1. Copy `.env.example` to `.env` and set only the API keys you need.
2. Start `uvicorn core.main:app --reload` from the repository root.
3. Open `http://localhost:8000/docs` and call `GET /models`.
4. Call `GET /models/catalog` for the editable model directory.
5. Call `POST /models/probe` with `{"model_id":"local-saluki"}`,
   `{"model_id":"cloud-groq"}` or `{"model_id":"cloud-gemini"}`.
   You can also test any custom catalog model by its ID.
6. The endpoint returns `status=ready` only after a real API request gives
   a valid geographic-intent JSON response. `configured=true` merely means
   credentials are present and is not a successful connectivity check.

Model-specific errors do not reveal API keys to the client. HTTP 409 means
missing configuration, HTTP 429 means quota exhaustion, and HTTP 502 means
a failed remote request or invalid response.

The application never automatically sends a user's request from one cloud
provider to the other without the user selecting the second profile. When no
model is usable, ordinary GIS operations remain available.

## Model evaluation and reproducibility

Run an optional benchmark suite using:
`python -m intelligence.benchmark --profile default` or
`python -m intelligence.benchmark --profile analysis`.

It uses only synthetic test prompts and records matching intent accuracy,
latency and any provider errors. It makes real billable/rate-limited API calls,
so run it only when you intend to consume your available quota.
No secret, chat history or geographic dataset is included in the benchmark.

The interface contract accepts future providers as long as they produce a
validated `locate` or `discover` action and non-fabricated target query.
