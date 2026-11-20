# AI model selection

GeoFathom has no proprietary model dependency. Its parser and tool dispatcher
can use any local OpenAI-compatible or Ollama model capable of returning short
structured JSON. Geospatial truth always comes from data and GIS algorithms.

## Preferred local model: Saluki 27B

Saluki 27B is an approximately 7.89 GB mixed-IQ2 GGUF release derived from
Qwen3.8-27B. The publisher emphasizes tool calling, but its public benchmarks
are limited. Quantization trades some accuracy for cost and smaller VRAM use.
Treat predictions as untrusted intent proposals and validate every action.

Reference: https://huggingface.co/ConwayResearch/Underdog-Saluki-27B-1.0

**Ollama**: Set GEOFATHOM_LLM_PROVIDER=ollama,
GEOFATHOM_LLM_MODEL=saluki, and GEOFATHOM_OLLAMA_URL=http://localhost:11434.
The `saluki` tag is an example local alias; check `ollama list` and set
the precise installed tag. GeoFathom neither downloads nor assumes model
weights are installed.

**llama.cpp**: Host your locally available GGUF with a compatible version of
`llama-server` and the appropriate Qwen chat template, then set
GEOFATHOM_LLM_PROVIDER=openai-compatible,
GEOFATHOM_OPENAI_BASE_URL=http://127.0.0.1:8080/v1,
and GEOFATHOM_LLM_MODEL to the identifier exposed by the server.

**No AI**: Set GEOFATHOM_LLM_PROVIDER=none and
GEOFATHOM_LLM_MODEL= to keep deterministic geographic lookup available.
If the configured model cannot be reached, the service uses rule-based
interpretation without fabricating any locations or measurements.

## Alternatives

- Existing Qwen 9B: lower latency, smaller resource use, suitable for simple
  intent normalization when thoroughly tested on local examples.
- Full-precision or higher-quantized Qwen 27B variants: potentially stronger
  complex reasoning, but significantly heavier memory and compute usage.
- Any future tool-capable model: implement IntentProvider or configure an
  OpenAI-compatible endpoint, while keeping the API independent of weights.

Saluki's optional vision projector provides image understanding; it is NOT a
pixel-accurate satellite segmentation engine. Automated polygon tracing still
requires a properly licensed imagery provider, georeferencing and a dedicated
vision adapter.

## Acceptance checks

Before selecting a model as the sole tool dispatcher, validate it against
real local prompts: bilingual place aliases, identical names in different
cities, impossible spatial queries, requested area filters, missing boundaries,
structured JSON compliance and refusal to fabricate coordinates.
Measure tool selection accuracy and error recovery, not just generic chat scores.
