# OTel Collector Strategy - Standardized GenAI Observability

The SUSE AI OTel Collector (`otelcol-suse-ai`) serves as the intelligent backbone for the observability extension. It must provide data that is 100% compatible with standard OTel backends while enabling high-level inference in SUSE Observability.

## 1. Resource Attribute Promotion (Standard First)

**Strategy**: Use the standard `transform` or `resource` processor to ensure that span-level GenAI context is reflected at the Resource level. This allows any OTel-compatible system to group metrics and traces by architectural components.

**Implementation**:
- Identify spans with `gen_ai.system` or `gen_ai.provider.name`.
- Copy these values to Resource attributes if missing.
- Aggregate `gen_ai.request.model` into a comma-separated `gen_ai.models` Resource attribute.
- **Why?**: This follows OTel's goal of "identity-carrying" resources and allows the StackPack to multiplex components.

## 2. Infrastructure Heartbeats (Semantic Conventions)

**Strategy**: Instead of custom topology elements, use standard OTel **Resource Metrics** to "heartbeat" the existence of infrastructure.

**Implementation**:
- For every Prometheus scraper target (Milvus, vLLM, etc.), ensure the metric's `Resource` contains:
    - `service.name`: The logical name (e.g., `milvus-standalone`).
    - `service.namespace`: The Kubernetes namespace.
    - `gen_ai.system` or `db.system`: To identify the type.
- Ensure these resources are sent to the `sts_topo_opentelemetry_collector` topic.
- **Why?**: Standard OTel agents use Resource attributes to describe the origin of telemetry. SUSE Observability will interpret these as topology nodes.

## 3. Metric Label Normalization

**Strategy**: Align custom metrics with GenAI Semantic Conventions.

**Implementation**:
- Normalize model-specific labels to `gen_ai.request.model` or `model_name`.
- Ensure a consistent `service_name` or `service.name` label across all metrics emitted by a component.
- Map system-specific latency metrics to standard histograms where possible.
