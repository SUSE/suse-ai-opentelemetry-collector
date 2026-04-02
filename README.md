# SUSE AI OpenTelemetry Collector

A custom [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/) distribution built with [OCB](https://opentelemetry.io/docs/collector/custom-collector/) for monitoring SUSE AI infrastructure.

It collects traces, metrics, and logs from GenAI components (Ollama, vLLM, Milvus, Open WebUI, etc.), normalizes them with `gen_ai.*` semantic conventions, and forwards the data to [SUSE Observability](https://www.suse.com/products/observability/).

## Components

The distribution bundles receivers, processors, exporters, and extensions from `opentelemetry-collector-contrib`, plus a custom **topology exporter** that infers the architectural map of GenAI applications, systems, and models from trace data.

See [`builder-config.yaml`](builder-config.yaml) for the full component manifest and [`collector-config.yaml`](collector-config.yaml) for a reference pipeline configuration.

## Building

Requires Go 1.24+ and the OTel Collector Builder:

```bash
go install go.opentelemetry.io/collector/cmd/builder@v0.147.0
builder --config builder-config.yaml
cd suse-ai-opentelemetry-collector && go build -o otelcol-custom .
```

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
