# Topology Exporter Design

## Summary

A custom OpenTelemetry exporter (`topologyexporter`) that discovers topology relationships from GenAI and database spans flowing through the collector, and pushes explicit components + relations to SUSE Observability's receiver API. This enables topology arrows between product components (e.g., app -> inference-engine -> llm-model) without requiring identifier-based merging with OTel service components.

## Motivation

The SUSE AI StackPack creates product components (inference engines, models, vector databases, etc.) from OTel telemetry, but these components lack topology relations in the UI. Previous approaches tried to merge product components with OTel service components via shared identifiers, but this caused product components to lose their custom types and appear as generic OTel services.

The topology exporter solves this by creating explicit relations between product components using the same externalId scheme, pushed via the receiver API to a dedicated sync in the StackPack.

## Architecture

### Data Flow

```
Traces (from instrumented apps)
    |
    | OTel pipeline (traces/topology)
    v
topologyexporter
    | Extracts: suse.ai.component.name/type, gen_ai.provider.name,
    |           gen_ai.request.model, db.system
    | Accumulates: components + relations in memory
    |
    | HTTP POST /receiver/stsAgent/intake (every flush_interval)
    v
SUSE Observability Receiver API
    |
    | Kafka topic (sts_topo_suse-ai_local)
    v
SUSE AI StackPack (Topology Sync)
    | Passthrough ID extractors
    | MergePreferTheirs (product sync data wins)
    v
Topology Graph
    [app] --uses--> [ollama] --runs--> [llama3.2]
```

### Component Type

OTel **exporter** — consumes traces, pushes to an external API. Not a connector (no data flows back into OTel pipelines) or processor (doesn't transform data in-flight).

### Optional Deployment

The exporter is opt-in. Users add a `traces/topology` pipeline to their collector config:

```yaml
exporters:
  topology/suseai:
    endpoint: https://suse-observability:7077
    api_key: ${SUSE_OBS_API_KEY}
    instance_type: suse-ai
    instance_url: local
    flush_interval: 60s
    namespace: ${SUSE_AI_NAMESPACE}
    tls:
      ca_file: /etc/ssl/certs/ca.crt
      insecure_skip_verify: false

service:
  pipelines:
    traces/topology:
      receivers: [routing/traces]
      processors: [filter/genai-spans]
      exporters: [topology/suseai]
```

Without this pipeline, the StackPack works normally — just no topology arrows between product components.

## Topology Discovery

### Component Discovery

Each span is inspected for resource and span attributes. Discovered components use the same externalId scheme as the product sync (`suse-ai:product:{type}:{name}`).

| Source | Attribute | Component Type | ExternalId |
|--------|-----------|---------------|------------|
| Resource | `suse.ai.component.name` + `suse.ai.component.type` | from type | `suse-ai:product:{type}:{name}` |
| Span | `gen_ai.provider.name` | `inference-engine` | `suse-ai:product:inference-engine:{provider}` |
| Span | `gen_ai.request.model` | `llm-model` | `suse-ai:product:llm-model:{model}` |
| Span | `db.system` where value is milvus or qdrant | `vectordb` | `suse-ai:product:vectordb:{system}` |
| Span | `db.system` where value is opensearch or elasticsearch | `search-engine` | `suse-ai:product:search-engine:{system}` |

Spans without `suse.ai.component.name` in their resource attributes are skipped. When `suse.ai.component.type` is missing, it defaults to `"application"` (matching the product ID extractor behavior). All `db.system` comparisons are case-insensitive.

### Relation Discovery

| Condition | Source -> Target | Type |
|-----------|-----------------|------|
| Span has `gen_ai.provider.name` | app -> inference-engine | `uses` |
| Span has `gen_ai.provider.name` AND `gen_ai.request.model` | inference-engine -> llm-model | `runs` |
| Span has `db.system` in {milvus, qdrant} | app -> vectordb | `uses` |
| Span has `db.system` in {opensearch, elasticsearch} | app -> search-engine | `uses` |

### Layer Assignment

| Component Type | Layer |
|---------------|-------|
| application, ui, agent | Applications |
| inference-engine, vectordb, search-engine | Services |
| llm-model | Models |

## Receiver API Payload

The exporter sends a full snapshot on each flush cycle.

### Component JSON

```json
{
  "externalId": "suse-ai:product:inference-engine:ollama",
  "type": {"name": "inference-engine"},
  "data": {
    "name": "ollama",
    "layer": "Services",
    "domain": "SUSE AI",
    "labels": ["suse.ai.component.type:inference-engine"],
    "identifiers": ["suse-ai:product:inference-engine:ollama"]
  }
}
```

### Relation JSON

```json
{
  "externalId": "suse-ai:product:application:open-webui --> suse-ai:product:inference-engine:ollama",
  "sourceId": "suse-ai:product:application:open-webui",
  "targetId": "suse-ai:product:inference-engine:ollama",
  "type": {"name": "uses"}
}
```

### Full Payload Structure

The `collection_timestamp` is Unix epoch in **seconds** (matching the v1.5.0 sidecar convention). The `internalHostname` is hardcoded to `"suse-ai-opentelemetry-collector"` — this is a source identifier, not a unique instance ID, so multiple collector instances can safely use the same value.

```json
{
  "collection_timestamp": 1711036800,
  "internalHostname": "suse-ai-opentelemetry-collector",
  "topologies": [{
    "start_snapshot": true,
    "stop_snapshot": true,
    "instance": {"type": "suse-ai", "url": "local"},
    "components": [...],
    "relations": [...]
  }],
  "events": {},
  "metrics": [],
  "service_checks": [],
  "health": []
}
```

## Flush Cycle

- Topology is accumulated in memory over a configurable window (default 60s)
- On each flush, the accumulator takes a snapshot (returns current state, resets to empty maps)
- The snapshot is sent as a full topology snapshot (`start_snapshot: true, stop_snapshot: true`)
- Components/relations that stop appearing naturally age out after the next flush
- **Empty flushes**: When the accumulator has zero components/relations, a snapshot with empty arrays is still sent. This correctly signals to the sync that no topology exists, allowing stale components to age out
- **Receiver unreachable**: The exporter logs a warning and retries on the next cycle. Topology is rebuilt from live traces each window, so no data is permanently lost. During outages, topology arrows temporarily disappear from the UI until connectivity is restored
- The exporter does NOT use `exporterhelper`'s built-in queue/retry because the accumulation pattern is fundamentally different from per-batch export — we batch across time (flush window), not per incoming batch

## Go Code Structure

```
suse-ai-opentelemetry-collector/topologyexporter/
  config.go          - Config struct, embeds configtls.ClientConfig
  factory.go         - OTel factory: NewFactory, createTracesExporter
  exporter.go        - Main exporter: start, shutdown, pushTraces, flush loop
  topology.go        - Thread-safe accumulator: processSpan, snapshot, reset
  receiver_client.go - HTTP client for /receiver/stsAgent/intake
  types.go           - Receiver API DTOs (Component, Relation, Topology, Payload)
```

### Config

```go
type Config struct {
    configtls.ClientConfig `mapstructure:"tls"`
    Endpoint               string        `mapstructure:"endpoint"`
    APIKey                 string        `mapstructure:"api_key"`
    InstanceType           string        `mapstructure:"instance_type"`
    InstanceURL            string        `mapstructure:"instance_url"`
    FlushInterval          time.Duration `mapstructure:"flush_interval"`
    Namespace              string        `mapstructure:"namespace"`
}

func (cfg *Config) Validate() error {
    if cfg.Endpoint == "" { return errors.New("endpoint is required") }
    if cfg.APIKey == "" { return errors.New("api_key is required") }
    if cfg.FlushInterval < 10*time.Second { return errors.New("flush_interval must be >= 10s") }
    return nil
}
```

The `namespace` field is used as metadata in component labels (e.g., `k8s.namespace.name:{namespace}`) to associate discovered topology with the SUSE AI namespace. It is NOT used in externalId construction.

### Exporter Lifecycle

1. `start()`: Create HTTP client with TLS from `configtls.ClientConfig`, start background flush goroutine on a `time.Ticker`
2. `pushTraces()`: For each span in the batch, extract attributes and call `accumulator.processSpan()`. Thread-safe via mutex.
3. Ticker fires: Call `accumulator.snapshot()` which atomically swaps maps (returns old, creates new empty). Send snapshot via `receiverClient.send()`.
4. `shutdown()`: Stop ticker, perform final flush, close HTTP client.

### Thread Safety

`pushTraces()` can be called concurrently by the collector framework. The `topologyAccumulator` uses a `sync.Mutex` to protect its component and relation maps. `snapshot()` swaps the maps under the lock — creates new empty maps and returns the old ones — so the flush goroutine and pushTraces() never contend on the same maps.

## StackPack Changes

A new DataSource + Sync is added to the existing SUSE AI StackPack in `synchronization.sty`.

### Kafka Topic

The receiver API creates a Kafka topic from the topology instance fields. With `instance.type = "suse-ai"` and `instance.url = "local"`, the topic name follows the receiver's convention (typically `sts_topo_suse-ai_local`). The DataSource must be configured to read from this exact topic.

### New Nodes (ID range: -1108 to -1120)

1. **DataSource** (-1108): Reads from the topology Kafka topic
2. **ExtTopology** (-1109): Links DataSource to Sync settings
3. **TopologySyncSettings** (-1110): Cleanup/batch settings
4. **Sync** (-1111): Processes topology with:
   - **Component ID extractor** (-1112): Passthrough — uses externalId as-is, reads `data.identifiers`
   - **Relation ID extractor** (-1113): Passthrough — uses externalId as-is
   - **Component template** (-1114): This sync needs its own template (not reused from the product sync) because the exporter sends `data.layer` as a plain string (e.g., `"Services"`). The template uses the Handlebars `getOrCreate` helper for ComponentType and Layer resolution from these strings.
   - **Relation template** (-1115): Uses `getOrCreate` for RelationType. Passes through sourceId, targetId.
   - **Default component action** (-1116): `SyncActionCreateComponent` with `MergePreferTheirs`
   - **Default relation action** (-1117): `SyncActionCreateRelation` with `MergePreferTheirs`
   - **Merge strategy**: `MergePreferTheirs` — set on the topology sync's actions, meaning "existing data (from the product sync) wins over my incoming lightweight data." The topology sync's primary contribution is relations, not component metadata.

Note: The `runs` RelationType does not need to be pre-defined in the StackPack. The `getOrCreate` helper in the relation template will auto-create it on first use. If a custom icon or display name is desired later, a RelationType node can be added to the STY files.

### Merge Ordering

If the topology sync creates a component before the product sync has seen it, a bare-bones component is created (name, layer, domain only). When the product sync later creates the same component with `MergePreferMine`, the product sync's richer data (type, monitors, metrics) overwrites the bare-bones version. This ordering is acceptable — the topology arrows exist immediately, and full component metadata arrives shortly after.

### What Doesn't Change

- Existing SUSE AI sync (instance components) — unchanged
- Existing SUSE AI Products sync (product components) — unchanged
- Component types, metric bindings, monitors — unchanged
- The topology sync is always provisioned but sits idle until the exporter starts pushing data

## Testing Strategy

1. **Unit tests** for `topologyAccumulator`: verify component/relation discovery from mock spans
2. **Unit tests** for `receiverClient`: verify payload serialization matches expected JSON format
3. **Integration test**: Run the exporter with a mock HTTP server, send sample traces, verify the topology snapshot contains expected components and relations
4. **End-to-end**: Deploy in test cluster, verify topology arrows appear in SUSE Observability UI

## Migration from v1.5.0 Sidecar

The v1.5.0 Go sidecar used a different externalId scheme (`urn:openlit:genai:system/{name}`) and pushed to the same receiver API with `instance.type = "suse-ai"`. If upgrading from v1.5.0:

1. Remove the old sidecar deployment
2. Deploy the updated suse-ai-opentelemetry-collector with the topology pipeline
3. The old topology will age out after the sync's expiry window
4. New topology with `suse-ai:product:*` externalIds will replace it

The old sidecar and new exporter should NOT run simultaneously — they use the same Kafka topic (`instance.type = "suse-ai"`), and the full-snapshot protocol means each flush replaces the entire topology. Running both would cause them to overwrite each other.

## Future Extensions

- **Metrics consumption**: Add `exporter.WithMetrics()` to also discover topology from `gen_ai_client_*` metric labels (for cases where traces are unavailable)
- **Additional relation types**: Discover more relation patterns from span attributes (e.g., RAG pipeline relations)
- **Component properties**: Enrich topology components with additional metadata from span attributes
