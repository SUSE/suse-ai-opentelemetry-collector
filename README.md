# SUSE AI OpenTelemetry Collector

A custom [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/) distribution built with [OCB](https://opentelemetry.io/docs/collector/custom-collector/) for monitoring SUSE AI infrastructure.

It is based on the **Kubernetes distribution** of the OpenTelemetry Collector, extended with the **Elasticsearch receiver** and an optional legacy **Topology exporter**. The default configuration collects traces, metrics, and logs from GenAI components (Ollama, vLLM, Milvus, Open WebUI, etc.), normalizes their resource attributes, and forwards standard OTLP telemetry to [SUSE Observability](https://www.suse.com/products/observability/) or another OTel backend.

## Components

The distribution starts from the [opentelemetry-collector-contrib Kubernetes distribution](https://github.com/open-telemetry/opentelemetry-collector-releases/tree/main/distributions/otelcol-k8s) and adds:

- **Elasticsearch receiver** -- scrapes cluster and node-level metrics from Elasticsearch and OpenSearch instances.
- **Topology exporter** (custom, in [`topologyexporter/`](topologyexporter/)) -- retained for existing deployments that explicitly enable the legacy receiver API integration. The default configuration uses standard resource telemetry for topology instead.

### Kubernetes distribution highlights

Because this collector inherits the K8s distribution, it ships with Kubernetes-native receivers and processors out of the box:

| Category | Notable components |
|---|---|
| **Receivers** | OTLP, Prometheus, Kubernetes Cluster/Events/Objects, Kubelet Stats, File Log, Journald, Host Metrics, Jaeger, Zipkin |
| **Processors** | K8s Attributes, Resource Detection, Batch, Memory Limiter, Filter, Transform, Tail Sampling, and more |
| **Exporters** | OTLP/HTTP, Debug, File, Load Balancing, OTel Arrow |
| **Extensions** | Health Check, K8s Observer, K8s Leader Elector, OAuth2, OIDC Auth, PProf, ZPages |
| **Connectors** | Service Graph, Span Metrics, Routing, Count, Failover, Round Robin |

See [`builder-config.yaml`](builder-config.yaml) for the full component manifest and [`collector-config.yaml`](collector-config.yaml) for a reference pipeline configuration.

Optional [workload observation overlays](examples/README.md) provide per-pod
HTTP availability checks and Ollama process residency metrics with real pod UID
identity. OpenSearch aggregate metrics remain separate from per-pod probes.

### Explicit client dependencies

`count/suse_ai_clients` accepts only CLIENT spans with an observed nonempty
`server.address` and explicitly resolved `suse.ai.peer.service.name`,
`suse.ai.peer.service.namespace` and `suse.ai.peer.cluster`. The peer cluster must
equal the caller's actual `k8s.cluster.name`; unresolved, ambiguous and cross-cluster
targets must not be assigned these attributes. Instrumentation must verify target
identities against the actual deployment, not infer them from a provider name.

Namespace normalization runs before the connector. Its per-batch delta observations
are converted to `suse.ai.service.calls` and use the same AI service relation mapping
as paired servicegraph observations. No server spans, target components or synthetic
Kubernetes metadata are created. Zero counts are filtered, so unrelated trace batches
cannot refresh an idle dependency. Both sources can observe one call; these gauges
serve topology freshness, not request-volume charts. Record peer attributes on one
provider CLIENT span only, not its native HTTP child.

Count is already included in this distribution at 0.160.0 (upstream alpha). The same
configuration is tested with Contrib 0.156.0. Services retain the companion's canonical
namespace/name identifiers, including its existing cross-cluster identity limitation.

### Database client observations

`transform/suse_ai_database` normalizes `db.system` to `db.system.name` on database
spans before the connectors run. On CLIENT spans only, it also maps legacy
`net.peer.name` / `net.peer.ip` / `net.peer.port` to `server.address` / `server.port`.
Nonempty canonical attributes win; no destination identity is promoted to the
calling resource, and no missing port or Kubernetes metadata is invented.

The AI StackPack can display unresolved Milvus, Qdrant, OpenSearch and Elasticsearch
endpoints as client-observed dependencies. A database system without an address
does not identify a destination. These observations are scoped to the caller and
endpoint and do not claim server metrics or health. To connect a known native
database service, configure an exact endpoint-to-service association with the
peer attributes described above. SDKs need only standard database attributes;
the Collector can provide the verified association. See the
[StackPack example](https://github.com/StackVista/suse-stackpacks/tree/feat-suse-ai-stackpack-v2/examples/suse-ai#databases-observed-from-client-spans)
for the configuration and identity/expiry policy.

## Building

Requires Go 1.26.0 or newer. The container and CI use Go 1.26.7. Build the checked-in distribution:

```bash
cd suse-ai-opentelemetry-collector
go build -mod=readonly -o otelcol-custom .
./otelcol-custom --version
```

The distribution version is `0.160.0`, matching the upstream collector release. It is set in `builder-config.yaml` and embedded in the generated executable. The update script keeps it aligned with the selected release tag.

To regenerate it from the manifest, install `go.opentelemetry.io/collector/cmd/builder@v0.160.0` and run `builder --config builder-config.yaml` from the repository root.

### Updating components

The script [`scripts/update-collector.sh`](scripts/update-collector.sh) downloads the official K8s and contrib manifests from the selected release tag, merges in the Elasticsearch receiver and local Topology exporter, then regenerates, builds, and validates the distribution. It requires Go, curl, jq, and Mike Farah's yq v4.

```bash
bash scripts/update-collector.sh v0.160.0
```

Omit the tag to select the latest stable release. If the new release needs a newer Go version than the Containerfile provides, the update fails with a message to update the build image before publishing.

### Container image

```bash
docker build -f Containerfile -t suse-ai-otelcol .
```

The image is published to `ghcr.io/suse/suse-ai-opentelemetry-collector` when collector source, configuration, or build inputs change on `main`, and on published releases. Both amd64 and arm64 images are built. Each image build validates its bundled collector configuration.

## Running

The default configuration is for a Kubernetes gateway. Supply the deployment variables below and mount `collector-config.yaml` when overriding the image's bundled configuration.

```bash
# From the repository root, after building locally:
./suse-ai-opentelemetry-collector/otelcol-custom validate --config collector-config.yaml
./suse-ai-opentelemetry-collector/otelcol-custom --config collector-config.yaml
```

| Variable | Default / purpose |
| --- | --- |
| `API_KEY` | Required SUSE Observability API key; sent in the OTLP authorization header |
| `K8S_CLUSTER_NAME` | `local`; set this to the actual cluster name |
| `SUSE_AI_NAMESPACE` | `suse-private-ai`; application discovery and explicitly configured product namespace |
| `OTLP_ENDPOINT` | `suse-observability-otel-collector.suse-observability.svc.cluster.local:4317` |
| `OTLP_INSECURE` | `true` for the default in-cluster plaintext gRPC endpoint; use `false` for TLS |
| `VLLM_METRICS_PORT` | `8000`; discovered vLLM service port |
| `MILVUS_METRICS_ENDPOINT` | `milvus.<SUSE_AI_NAMESPACE>.svc.cluster.local:9091` |
| `QDRANT_METRICS_ENDPOINT` | `qdrant.<SUSE_AI_NAMESPACE>.svc.cluster.local:6333` |
| `GPU_NAMESPACE` / `GPU_METRICS_PORT` | `gpu-operator` / `9400`; DCGM exporter discovery |
| `ELASTICSEARCH_ENDPOINT` | `http://opensearch-cluster-master-headless.<SUSE_AI_NAMESPACE>.svc.cluster.local:9200`; set an HTTPS URL for secured clusters |
| `ELASTICSEARCH_USERNAME` / `ELASTICSEARCH_PASSWORD` | `admin` / required password for the configured search cluster |
| `ELASTICSEARCH_SERVICE_NAME` / `ELASTICSEARCH_SYSTEM` | `opensearch` / `opensearch`; use `elasticsearch` for an Elasticsearch deployment |

The Kubernetes service account needs read access (`get`, `list`, `watch`) to pods and their workload owners for enrichment, and services/endpoints for Prometheus discovery. Include namespaces, nodes, ReplicaSets, Deployments, StatefulSets, DaemonSets, Jobs, and CronJobs for the configured metadata extraction. Existing `service.namespace` takes precedence; otherwise the pod's namespace is used, followed by `default` for resources without a namespace. Kubernetes cluster identity is added only when pod or node metadata is present. A trace without Kubernetes metadata is still exported.

Remove unused scraper receivers and their pipelines when the corresponding infrastructure is not deployed. To use another OTLP backend, configure its endpoint, TLS, and authorization headers in the exporter. Configure the receiving SUSE Observability OTel collector to supply resource topology to `sts_topo_opentelemetry_collector`; the SUSE AI collector sends OTLP and does not publish directly to Kafka. Verify the integration with `sts topology-sync list` and `sts topology-sync describe` against that backend.

The collector exposes OTLP on **4317** (gRPC) and **4318** (HTTP), Jaeger on **14250** (gRPC) and **14268** (Thrift HTTP), and a health endpoint on **13133**.

## Telemetry behavior

Each original trace, metric, and log follows a single OTLP export path. The `span_metrics` connector separately generates `otel_span.*` request metrics. The default configuration preserves trace IDs, span IDs, service identity, host identity, and existing canonical GenAI values. It has no sampling or Kubernetes-presence filter.

Native v2 mappings retain model usage from original GenAI spans and SDK metrics.
Application details link to usage by service identity without adding a direct
application-to-model communication edge or a Count connector. The Service Graph connector produces
`suse.ai.service.calls` for real paired CLIENT/SERVER spans. Cumulative-to-delta
conversion and zero-increment filtering prevent its cache from refreshing idle
relationships. These gauges describe observations, not billing or request-rate
measurements. Keep both sides of each trace on the same Collector instance;
multiple gateways require trace-aware routing.

Span duration histograms use seconds and include service namespace and instance
identity. Disable the `span_metrics` connector in both pipelines if another
gateway already generates the same measurements.

Span and metric context is promoted to missing resource attributes. Distinct model names are appended to the comma-separated `gen_ai.models` value within each resource batch, preserving existing entries. This is batch aggregation, not persistent model inventory. Legacy PascalCase attributes and `gen_ai.system` are accepted; span-level provider values take precedence over a resource-level legacy-system fallback when the resource provider is missing.

A nonempty `gen_ai.agent.name` takes precedence over legacy naming. When the
canonical name is absent or empty, a nonempty `traceloop.entity.name` is copied
only for `traceloop.span.kind=agent`. Unusable names do not create named agents.
Missing and empty `service.namespace` values are normalized before connectors
and export: use a nonempty actual `k8s.namespace.name`, otherwise `default`.
Nonempty service namespaces are preserved, and existing `service_namespace`
metric labels follow the normalized resource. For example, an empty service
namespace in pod namespace `team-a` becomes `team-a`; an explicit `team-b` wins.
No Kubernetes metadata is fabricated for external workloads. Stock OpenTelemetry
0.1.4 still requires cluster metadata in its base mappings; this Collector
normalization does not fix that separate companion limitation.

Scraped vLLM resources carry `gen_ai.system` and `gen_ai.provider.name`; Milvus, Qdrant, and OpenSearch carry `db.system` and `db.system.name`. Known product scrapes set `suse.ai.product` for the v2 presentations. vLLM discovery scrapes individual pod endpoints and uses their pod UID as the instance identity; configure the SDK with that same UID and service identity. Static targets retain their supplied target identity without invented Kubernetes metadata. DCGM discovery supplies node identity and normalizes workload pod labels for GPU charts. GPU exporter resources use `hw.type=gpu`. Native metric names, including `vllm:`, and histogram buckets are preserved. vLLM's `model_name` is also available as `gen_ai.request.model`.

## Validation

```bash
cd topologyexporter
go test -mod=readonly -race ./...
go vet ./...
cd ..
python3 -m pip install -r tests/requirements.txt
python3 tests/test_collector.py --collector ./suse-ai-opentelemetry-collector/otelcol-custom
```

The integration tests run the actual collector against localhost endpoints and check traces, logs, metric normalization, model aggregation, resource identity, and scraper histograms. They replace Kubernetes discovery/enrichment and the Elasticsearch API input for isolation; deployment RBAC, credentials, and downstream synchronization still require a connected cluster. CI also runs the exporter tests under the generated collector's dependency versions.

The optional topology exporter supports a positive `timeout` (default `10s`), cancels outstanding requests during shutdown, and masks its API key in configuration output and transport errors. Its stream identity is fixed to `suse-ai/collector`; `cluster_name` supplies a metadata label. The removed `instance_url` option is not supported.

## Architecture

See [`ARCH.md`](ARCH.md) for a detailed description of the three-layer observability approach (instrumentation, collection, and virtual topology).

## Optional LiteLLM receiver

The image includes `/otelcol/litellm-receiver.yaml`. Enable it with both
`--config=/otelcol/collector-config.yaml --config=/otelcol/litellm-receiver.yaml`.
Set the actual `K8S_CLUSTER_NAME` and `LITELLM_NAMESPACE` (default `suse-private-ai`);
`LITELLM_SERVICE_NAME`, `LITELLM_K8S_SERVICE_NAME`, and `LITELLM_METRICS_PORT` default
to `litellm`, `litellm-router`, and `4000`. Grant the service account read access
to services/endpoints/pods in that namespace. This adds a separate metrics pipeline.

Enable LiteLLM's `prometheus` callback and configure access to `/metrics/`. Either
allow unauthenticated private metrics via `require_auth_for_metrics_endpoint: false`
or configure scrape authorization. Use a single scrape owner. Pod UIDs provide
real replica identity; native metric labels and cumulative counters are retained.
When also using LiteLLM's `otel` callback, configure matching service namespace/name
and instance identity in the SDK.
