# Monitoring OpenSearch in SUSE AI

## Overview
OpenSearch is used as a vector database or search engine in the SUSE AI stack.

## Instrumentation
- **Metrics**: Collected via the OpenTelemetry Collector's `elasticsearchreceiver` (OpenSearch is compatible with the Elasticsearch API).
- **Traces**: Not standard for OpenSearch itself, but client-side tracing (e.g., in a Python app) should use `db.system: opensearch`.

## Configuration (OTel Collector)
```yaml
receivers:
  elasticsearch:
    endpoint: "http://opensearch-cluster:9200"
    collection_interval: 15s
```

## Standard Attributes
- `db.system`: `opensearch`
- `db.operation`: `query`, `index`, `delete`, etc.
- `server.address`: The endpoint of the OpenSearch cluster.

## SUSE Observability Integration
- Ensure `service.name` is set to identify the cluster.
- Use `service.namespace` for logical grouping.
