# Monitoring vLLM in SUSE AI

## Overview
vLLM is a high-throughput LLM serving engine.

## Instrumentation
- **Metrics**: Exposes Prometheus metrics at `:8000/metrics`.
- **Naming**: Metric names start with `vllm:`.

## Configuration (OTel Collector)
```yaml
receivers:
  prometheus:
    config:
      scrape_configs:
        - job_name: 'vllm'
          kubernetes_sd_configs:
            - role: service
          relabel_configs:
            - source_labels: [__meta_kubernetes_service_name]
              action: keep
              regex: '.*vllm.*'
```

## Standard Attributes
- `gen_ai.system`: `vllm`
- `service.name`: `vllm`

## Decisions
- **Metric Naming**: For this version, we keep the original `vllm:` prefix (no renaming to `vllm_`).
