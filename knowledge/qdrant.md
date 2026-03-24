# Monitoring Qdrant (Quadrant) in SUSE AI

## Overview
Qdrant is a vector database (referred to as "quadrant" in some documentation).

## Instrumentation
- **Metrics**: Qdrant exposes metrics at `:6333/metrics`.
- **Traces**: Client-side instrumentation for database calls.

## Configuration (OTel Collector)
```yaml
receivers:
  prometheus:
    config:
      scrape_configs:
        - job_name: 'qdrant'
          static_configs:
            - targets: ['qdrant:6333']
```

## Standard Attributes
- `db.system`: `qdrant`
- `db.operation`: `search`, `upsert`, `recommend`.

## Topology
- Identified as a `Vector Database` node.
- Monitored for search latency and collection health.
