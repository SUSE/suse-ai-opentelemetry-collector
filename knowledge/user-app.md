# Generic User Application Instrumentation

## Overview
How to instrument custom AI applications to ensure compatibility with SUSE AI Observability.

## Instrumentation Techniques
1. **OpenTelemetry SDK**: Standard way for Python, JS, Go, etc.
2. **OpenLIT**: A wrapper for OTel that simplifies GenAI instrumentation.

## Required Resource Attributes
To be recognized as a SUSE AI component, the resource must include:
- `service.name`: Logical name of your app.
- `service.namespace`: Recommended to be `suse-ai` or your project name.
- `telemetry.sdk.name`: `openlit` or `suse-ai`.

## Required Span Attributes (GenAI)
For chat/completion operations:
- `gen_ai.operation.name`: `chat`
- `gen_ai.system`: (e.g., `ollama`, `vllm`, `openai`)
- `gen_ai.request.model`: (e.g., `llama3`)
- `gen_ai.usage.input_tokens`: (int)
- `gen_ai.usage.output_tokens`: (int)

## Example (Python with OTel)
```python
from opentelemetry import trace

tracer = trace.get_tracer(__name__)

with tracer.start_as_current_span("chat_operation") as span:
    span.set_attribute("gen_ai.operation.name", "chat")
    span.set_attribute("gen_ai.system", "ollama")
    span.set_attribute("gen_ai.request.model", "llama3")
    # ... call model ...
    span.set_attribute("gen_ai.usage.input_tokens", 50)
    span.set_attribute("gen_ai.usage.output_tokens", 120)
```
