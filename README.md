# SUSE AI OpenTelemetry Collector

A custom [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/) distribution built with [OCB](https://opentelemetry.io/docs/collector/custom-collector/) for monitoring SUSE AI infrastructure.

It is based on the **Kubernetes distribution** of the OpenTelemetry Collector, extended with the **Elasticsearch receiver** and a custom **Topology exporter**. It collects traces, metrics, and logs from GenAI components (Ollama, vLLM, Milvus, Open WebUI, etc.), normalizes them with `gen_ai.*` semantic conventions, and forwards the data to [SUSE Observability](https://www.suse.com/products/observability/).

## Components

The distribution starts from the [opentelemetry-collector-contrib Kubernetes distribution](https://github.com/open-telemetry/opentelemetry-collector-releases/tree/main/distributions/otelcol-k8s) and adds:

- **Elasticsearch receiver** -- scrapes cluster and node-level metrics from Elasticsearch and OpenSearch instances.
- **Topology exporter** (custom, in [`topologyexporter/`](topologyexporter/)) -- infers the architectural map of GenAI applications, inference engines, models, vector databases, and search engines from trace data and pushes it to SUSE Observability.

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

Requires Go 1.24+ and the OTel Collector Builder:

```bash
go install go.opentelemetry.io/collector/cmd/builder@v0.147.0
builder --config builder-config.yaml
cd suse-ai-opentelemetry-collector && go build -o otelcol-custom .
```

### Updating components

The script [`scripts/update-collector.sh`](scripts/update-collector.sh) fetches the latest OTel release, downloads the official K8s and contrib manifests, merges in the Elasticsearch receiver and the local Topology exporter, and regenerates `builder-config.yaml`.

### Container image

```bash
docker build -f Containerfile -t suse-ai-otelcol .
```

The image is also published to `ghcr.io/SUSE/suse-ai-opentelemetry-collector` on every push to `main`.

## Running

```bash
./otelcol-custom --config collector-config.yaml
```

The collector exposes OTLP on ports **4317** (gRPC) and **4318** (HTTP).

## Architecture

See [`ARCH.md`](ARCH.md) for a detailed description of the three-layer observability approach (instrumentation, collection, and virtual topology).
