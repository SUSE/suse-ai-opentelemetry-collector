# Monitoring Open WebUI in SUSE AI

## Overview
Open WebUI is the user interface for interacting with LLMs.

## Instrumentation
- **SUSE AI Filter**: A Python-based pipeline filter that instruments chat requests.
- **Metrics**: Emits GenAI usage metrics (tokens, cost, duration).
- **Traces**: Generates parent spans for chats and child spans for requests/responses.

## Configuration
- Environment variable `OTEL_EXPORTER_HTTP_OTLP_ENDPOINT` points to the OTel Collector.
- `telemetry.sdk.name`: `suse-ai`.

## Standard Attributes (GenAI)
- `gen_ai.operation.name`: `chat`
- `gen_ai.system`: `ollama`, `vllm`, `openai`, etc. (based on provider)
- `gen_ai.request.model`: The requested model name.
- `gen_ai.usage.input_tokens`: Tokens in the prompt.
- `gen_ai.usage.output_tokens`: Tokens in the completion.

## Information Available
- **Metadata**: `chat_id`, `user_id`, `model_pricing`.
- **Topology**: Connects the WebUI to the AI System (e.g., Ollama) via `gen_ai.system`.
