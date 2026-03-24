# Monitoring Ollama in SUSE AI

## Overview
Ollama is a tool for running LLMs locally.

## Instrumentation
- **Metrics**: Ollama exposes basic metrics (if configured) or is monitored via the consumer (Open WebUI).
- **Traces**: Typically traced at the client level (Open WebUI or custom app).

## Standard Attributes
- `gen_ai.system`: `ollama`
- `gen_ai.operation.name`: `chat`, `generate`

## Topology
- Represented as a `GenAI System` node in SUSE Observability.
- Linked to `GenAI Model` nodes based on the `gen_ai.request.model` attribute.
