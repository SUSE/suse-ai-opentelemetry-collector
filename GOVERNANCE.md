# Governance and Execution Plan - SUSE AI Observability

## Architectural Decisions

### 1. Telemetry Naming & Semantics
- **vLLM Metrics**: We will preserve the `vllm:` prefix for metrics. This ensures compatibility with existing dashboards that expect this specific naming convention.
- **Grouping Attribute**: Instead of the custom `stackpack: suse-ai` attribute, we will adopt the standard OpenTelemetry `service.namespace` attribute, set to `suse-ai`.
- **SDK Identity**: Components developed or specifically instrumented for SUSE AI will use `telemetry.sdk.name: suse-ai`.
- **Normalization**: All custom or legacy attributes (e.g., `GenAiSystem`) will be mapped to their standardized OTel equivalents (e.g., `gen_ai.system`) using the `transform` processor.

### 2. Topology Generation
- **Promotion Logic**: To enable SUSE Observability to build an architectural map, the collector will "promote" key span/metric attributes to Resource-level attributes:
    - `gen_ai.system` -> Resource Attribute
    - `db.system` -> Resource Attribute
    - `gen_ai.request.model` -> Aggregated into `gen_ai.models` Resource Attribute.

### 3. Component Coverage
The following components are officially supported in the pipeline:
- **Search/Vector DB**: OpenSearch, Milvus, Qdrant.
- **AI Engines**: Ollama, vLLM.
- **Orchestration/Proxy**: LiteLLM, Open WebUI.

---

## Execution Plan

### Phase 1: Preparation (Completed)
- [x] Gather context from SUSE AI documentation.
- [x] Analyze `suse_ai_filter.py` for Open WebUI instrumentation patterns.
- [x] Create `knowledge/` documentation for each component.

### Phase 2: Collector Manifest Update (Completed)
- [x] Review `builder-config.yaml`.
- [x] Ensure `transformprocessor`, `resourceprocessor`, `elasticsearchreceiver`, and `prometheusreceiver` are included.
- [x] Verified that all necessary components for SUSE AI are present in the manifest.

### Phase 3: Pipeline Configuration Implementation (Completed)
- [x] **Receivers**: Defined scrape jobs for vLLM, Milvus, Qdrant, and GPU Metrics. Added Elasticsearch for OpenSearch.
- [x] **Processors**:
    - [x] Implemented `k8sattributes` and `resourcedetection`.
    - [x] Created `transform` logic for attribute normalization (Legacy -> OTel) and promotion (Span/Metric -> Resource).
    - [x] Configured `resource` processor to set `service.namespace: suse-ai` and `suse.ai.component` identity.
- [x] **Exporters**: Set up OTLP export to SUSE Observability and detailed debug logging.


### Phase 4: Validation & Testing (Completed)
- [x] Verified that `collector-config.yaml` addresses all semantic convention and topology requirements.
- [x] Confirmed `vllm:` metrics preservation.
- [x] Validated `service.namespace: suse-ai` transition.
- [x] Documented all components in the `knowledge/` folder.
