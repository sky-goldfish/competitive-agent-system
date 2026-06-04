# Architecture

MVP uses a two-stage orchestration around LangGraph-compatible nodes:

1. `start_run`: requirement understanding -> competitor discovery -> human confirmation wait
2. `confirm_and_continue_run`: material collection -> structured analysis -> report generation

The implementation stores all run data in SQLite and exposes FastAPI endpoints for the React frontend.

## LLM providers

The backend supports these `LLM_PROVIDER` values:

- `mock`: local deterministic provider for development and tests.
- `ark`: Volcengine Ark through its OpenAI-compatible endpoint.
- `openai`, `openai_compatible`, or `openai-compatible`: any OpenAI Chat Completions-compatible endpoint.

To use an OpenAI-compatible endpoint:

```env
LLM_PROVIDER=openai
OPENAI_API_KEY=your-api-key
OPENAI_MODEL=your-model-name
OPENAI_BASE_URL=https://api.openai.com/v1
OPENAI_TEMPERATURE=0.2
```

`OPENAI_BASE_URL` can point to the official OpenAI API or a third-party compatible service. For a local endpoint without authentication, provide any placeholder `OPENAI_API_KEY` value because the OpenAI SDK requires one.

`OPENAI_MODEL` must be set explicitly. `OPENAI_TEMPERATURE` is optional; omit it for compatible reasoning models or services that reject the parameter.
