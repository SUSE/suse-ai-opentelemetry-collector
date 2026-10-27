# Optional workload observations

These overlays extend `collector-config.yaml` using standard receivers already
included in the Collector. The image bundles `litellm-receiver.yaml`,
`ollama-runtime.yaml` and `workload-probes.yaml` in `/otelcol/`, beside the base
config. Enable a profile by passing a separate `--config` argument for its
bundled path; no download is needed. Profiles are optional and are not enabled
by the image's default command. Mount a customized copy when you need to remove
unused product rules or auth extensions.

```bash
docker run --rm \
  -e API_KEY -e ELASTICSEARCH_PASSWORD -e K8S_CLUSTER_NAME \
  registry.suse.com/ai/containers/suse-ai-opentelemetry-collector:0.164.0 \
  validate --config=/otelcol/collector-config.yaml \
  --config=/otelcol/litellm-receiver.yaml \
  --config=/otelcol/ollama-runtime.yaml \
  --config=/otelcol/workload-probes.yaml
```

The registry tag is the intended release target; publication follows the SUSE
registry release process. For local source builds:

```bash
./suse-ai-opentelemetry-collector/otelcol-custom validate \
  --config collector-config.yaml --config examples/workload-probes.yaml \
  --config examples/ollama-runtime.yaml
```

Use one scrape owner. When combining other overlays, retain all needed
`service.extensions` entries because Collector configuration merging replaces
lists. Keep existing product aggregate receivers on their own pipelines.

## Per-pod availability probes

`workload-probes.yaml` discovers declared pod ports through `k8s_observer` and
creates `http_check` receivers with `receiver_creator`. It probes each actual pod
address, so replicas cannot alternate behind a shared Service endpoint. Pods
must have the product labels and declared ports used in the rules.

| Product | Pod label / port | Read-only probe |
| --- | --- | --- |
| Ollama | `app.kubernetes.io/name=ollama`, 11434 | `/api/tags` |
| MCPO | `app.kubernetes.io/name=open-webui-mcpo`, 8000 | `/openapi.json` |
| MLflow | `app.kubernetes.io/name=mlflow`, 5000 | `/health` |
| Model Registry | `app.kubernetes.io/component=model-registry-server`, 8080 | `/api/model_registry/v1alpha3/registered_models` with service-account auth |
| OpenSearch | `app.kubernetes.io/name=opensearch`, 9200 | HTTPS `/` with basic auth |

Set `K8S_CLUSTER_NAME` to the actual cluster identity. Product namespace variables
are `OLLAMA_NAMESPACE`, `MCPO_NAMESPACE`, `MLFLOW_NAMESPACE`,
`MODEL_REGISTRY_NAMESPACE` and `OPENSEARCH_NAMESPACE`. All default to
`suse-private-ai` except Model Registry (`kubeflow`). Configure the matching
`*_SERVICE_NAME` variables to match existing telemetry; OpenSearch uses
`ELASTICSEARCH_SERVICE_NAME`. `MCPO_HEALTH_PATH` defaults to `/openapi.json`; use
a real available route, not an assumed `/health` endpoint.

The Collector service account needs `get/list/watch` on the selected pods, plus
the base enrichment permissions. The Model Registry endpoint also requires
authorization for this service account in the target installation. OpenSearch
uses `ELASTICSEARCH_USERNAME` and `ELASTICSEARCH_PASSWORD`; supply a trusted
`OPENSEARCH_CA_FILE` and `OPENSEARCH_TLS_SERVER_NAME` when pod IPs are not in the
server certificate. TLS verification stays enabled.

Each probe carries `suse.ai.observation.kind=http-probe`, the real pod UID as
`service.instance.id`, the actual pod namespace as `service.namespace`, and
actual Kubernetes pod/name/node metadata. Product attributes identify the
explicitly configured server being probed. The observations describe an HTTP
probe, not application request latency or traffic. MCPO uses the explicit
`mcp-server` category. Model Registry UI pods and other applications are excluded.

OpenSearch cluster/node metrics from the Elasticsearch receiver remain aggregate
observations. They must not receive an arbitrary pod's identity; the independent
HTTP probe provides workload-instance identity without changing their meaning.
Replace prior Service-level probes for these same products to avoid redundant
availability streams. Existing native application OTLP needs no probe merely to
obtain pod identity.

## Ollama process residency

`ollama-runtime.yaml` scrapes the `ollama-metrics` port of actual Ollama pods.
Install the read-only sidecar from the observability extension's
`integrations/ollama` directory. It exposes `ollama_api_up`,
`ollama_loaded_models`, `ollama_model_size_bytes`, `ollama_model_vram_bytes` and
`ollama_model_context_length`. The latter three retain the `model` label.
These are Ollama-reported allocations/residency and context, not utilization,
request counts, generated tokens or cost. Missing/error snapshots are not cached.

The scrape uses the same `OLLAMA_NAMESPACE`, `OLLAMA_SERVICE_NAME` and actual
cluster configuration as the probe. It preserves real pod UID/name/node identity
and marks the product as Ollama. No topology exporter or served-model topology is
introduced. Gate charts on a currently healthy `ollama_api_up` per instance.

## Tests

```bash
python3 tests/test_workload_collection.py \
  --collector ./suse-ai-opentelemetry-collector/otelcol-custom
```

The tests run the actual Collector against a local Kubernetes API and HTTP
fixtures. They exercise Kubernetes watch discovery, dynamic receiver creation,
pod UID/node enrichment, product/namespace filters, replicas, Model Registry
authentication and runtime metric values. They do not replace deployment RBAC,
real endpoint credentials or backend topology verification. The same overlays
are validated unmodified against the base config before fixture substitution.
