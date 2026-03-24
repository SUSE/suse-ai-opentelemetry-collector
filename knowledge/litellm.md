# Monitoring LiteLLM in SUSE AI

## Overview
LiteLLM is a proxy for various LLM providers (Ollama, vLLM, OpenAI, etc.).

## Instrumentation
- **Metrics/Traces**: LiteLLM can be configured to export OTel telemetry directly.
- **Role**: Acts as a gateway, providing a unified API.

## Standard Attributes
- `gen_ai.system`: `litellm`
- `gen_ai.provider.name`: The actual provider being proxied (e.g., `openai`, `anthropic`).

## Topology
- Acts as a bridge between the Application and the specific AI Providers.
- Useful for tracking costs across multiple backends.
