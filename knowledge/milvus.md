# Monitoring Milvus in SUSE AI

## Overview
Milvus is a high-performance vector database.

## Instrumentation
- **Metrics**: Milvus exposes a Prometheus endpoint at `:9091/metrics`.
- **Traces**: Milvus supports Jaeger-compatible tracing, which can be sent to the OTel Collector.

## Configuration (OTel Collector)
```yaml
receivers:
  prometheus:
    config:
      scrape_configs:
        - job_name: 'milvus'
          static_configs:
            - targets: ['milvus:9091']
```

## Standard Attributes
- `db.system`: `milvus`
- `db.operation`: `search`, `insert`, `query`.
- `db.collection.name`: Name of the collection being accessed.

## SUSE Observability Integration
- Topology nodes are generated from `db.system: milvus`.
- Heartbeats are captured via the existence of metrics with `service.name: milvus`.
