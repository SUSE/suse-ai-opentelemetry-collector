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
| `SUSE_AI_NAMESPACE` | `suse-private-ai`; application discovery and fallback namespace |
| `OTLP_ENDPOINT` | `suse-observability-otel-collector.suse-observability.svc.cluster.local:4317` |
| `OTLP_INSECURE` | `true` for the default in-cluster plaintext gRPC endpoint; use `false` for TLS |
| `VLLM_METRICS_PORT` | `8000`; discovered vLLM service port |
| `MILVUS_METRICS_ENDPOINT` | `milvus.<SUSE_AI_NAMESPACE>.svc.cluster.local:9091` |
| `QDRANT_METRICS_ENDPOINT` | `qdrant.<SUSE_AI_NAMESPACE>.svc.cluster.local:6333` |
| `GPU_NAMESPACE` / `GPU_METRICS_PORT` | `gpu-operator` / `9400`; DCGM exporter discovery |
| `ELASTICSEARCH_ENDPOINT` | `http://opensearch-cluster-master-headless.<SUSE_AI_NAMESPACE>.svc.cluster.local:9200`; set an HTTPS URL for secured clusters |
| `ELASTICSEARCH_USERNAME` / `ELASTICSEARCH_PASSWORD` | `admin` / required password for the configured search cluster |
| `ELASTICSEARCH_SERVICE_NAME` / `ELASTICSEARCH_SYSTEM` | `opensearch` / `opensearch`; use `elasticsearch` for an Elasticsearch deployment |

The Kubernetes service account needs read access (`get`, `list`, `watch`) to pods and their workload owners for enrichment, and services/endpoints for Prometheus discovery. Include namespaces, nodes, ReplicaSets, Deployments, StatefulSets, DaemonSets, Jobs, and CronJobs for the configured metadata extraction. Existing `service.namespace` takes precedence; otherwise the pod's namespace is used before the deployment fallback. A trace without Kubernetes metadata is still exported.

Remove unused scraper receivers and their pipelines when the corresponding infrastructure is not deployed. To use another OTLP backend, configure its endpoint, TLS, and authorization headers in the exporter. Configure the receiving SUSE Observability OTel collector to supply resource topology to `sts_topo_opentelemetry_collector`; the SUSE AI collector sends OTLP and does not publish directly to Kafka. Verify the integration with `sts topology-sync list` and `sts topology-sync describe` against that backend.

The collector exposes OTLP on **4317** (gRPC) and **4318** (HTTP), Jaeger on **14250** (gRPC) and **14268** (Thrift HTTP), and a health endpoint on **13133**.

## Telemetry behavior

Each original trace, metric, and log follows a single OTLP export path. The `span_metrics` connector separately generates `otel_span.*` request metrics. The default configuration preserves trace IDs, span IDs, service identity, host identity, and existing canonical GenAI values. It has no sampling or Kubernetes-presence filter.

Span and metric context is promoted to missing resource attributes. Distinct model names are appended to the comma-separated `gen_ai.models` value within each resource batch, preserving existing entries. This is batch aggregation, not persistent model inventory. Legacy PascalCase attributes and `gen_ai.system` are accepted; span-level provider values take precedence over a resource-level legacy-system fallback when the resource provider is missing.

Scraped vLLM resources carry `gen_ai.system` and `gen_ai.provider.name`; Milvus, Qdrant, and OpenSearch carry `db.system` and `db.system.name`. Each scraper preserves its target instance identity and adds service and namespace context. GPU exporter resources use `hw.type=gpu`. Native metric names, including `vllm:`, and histogram buckets are preserved. vLLM's `model_name` is also available as `gen_ai.request.model`.

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
