# SUSE AI Observability Architecture

This document describes the architectural approach for the SUSE AI Observability Extension, a specialized layer built on top of SUSE Observability (formerly StackState) to provide deep insights into Generative AI systems.

## 1. Overview

SUSE AI Observability transforms raw OpenTelemetry (OTel) telemetry into a high-level, architectural map of GenAI components. It moves beyond simple "services" and "pods" to represent the logical structure of AI applications, LLM providers, and specific models.

## 2. Layers of the Solution

### Layer 1: Contextualized Instrumentation
SUSE AI components (Milvus, Open WebUI, vLLM, Ollama) are deployed with pre-configured OTel instrumentation. We use Helm charts and Rancher extensions to inject:
- `OTEL_RESOURCE_ATTRIBUTES`: Standardized metadata like `gen_ai.application_name`, `gen_ai.system`, and `stackpack: suse-ai`.
- `suse-ai` SDK Identity: Distinguishes SUSE-provided telemetry from generic data.
- **Smart Filters**: The `suse_ai_filter` processes spans in real-time to calculate costs and aggregate model usage into Resource-level attributes.

### Layer 2: Intelligent Collection
A custom OTel collector (`otelcol-suse-ai`) normalizes incoming telemetry.
- **Prometheus Scrapers**: Pulls deep metrics from infrastructure components (Milvus, vLLM, OpenSearch).
- **Topology Promotion**: (Planned) The collector "promotes" the existence of logical components by emitting topology elements based on the presence of specific metrics, ensuring observability even when trace data is sparse.

### Layer 3: Virtual Topology (StackPack)
The StackPack implements a "Multiplexed Sync" strategy to build the graph:
- **Abstraction over Complexity**: It hides low-level constructs like `service-instance` (Pods) from primary views, presenting a clean "Architectural View".
- **Multiplexed Mapping**: A single OTel payload (e.g., from an App) can trigger the creation of the Application node, the System node it uses (e.g., Ollama), and the specific Models being executed.
- **Inferred Relations**:
    - `uses`: Links consumer Apps to AI Systems based on `gen_ai.system` attributes.
    - `runs`: Links AI Systems to Models based on `gen_ai.models` aggregation.
    - `provided-by`: Connects the high-level logical abstraction to the underlying physical infrastructure.

## 3. Component Hierarchy

1.  **GenAI App**: Consumer services (e.g., a Python chatbot, Open WebUI).
2.  **GenAI System**: Engines and Databases (e.g., Ollama, vLLM, Milvus).
3.  **GenAI Model**: The specific AI model being served (e.g., Llama-3, GPT-4).

## 4. Design Philosophy

- **Simplicity First**: The UI should represent how a human architect thinks about the system, not how Kubernetes schedules it.
- **Bound Observability**: Metrics and Monitors are bound directly to the logical components they describe.
- **Dynamic Adaptability**: The topology updates automatically as new models are called or new apps are instrumented.
