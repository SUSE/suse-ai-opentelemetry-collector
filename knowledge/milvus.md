# Monitoring Milvus in SUSE AI

Collector 0.164.1 changes `/otelcol/milvus.yaml` from one static Service scrape
to Kubernetes endpoint discovery. Load the base configuration first, then this
profile. Set `K8S_CLUSTER_NAME` to the actual cluster identity.

| Variable | Default / behavior |
| --- | --- |
| `MILVUS_NAMESPACE` | `SUSE_AI_NAMESPACE`, default `suse-private-ai` |
| `MILVUS_K8S_SERVICE_NAME` | `milvus`; exact Kubernetes Service selector |
| `MILVUS_SERVICE_NAME` | `milvus`; logical native service name |
| `MILVUS_METRICS_PORT` | `9091`; pod endpoint metrics port |
| `MILVUS_METRICS_ENDPOINT` | Unset/empty: discovery. Nonempty `host:port`: static fallback only |
| `MILVUS_TARGET_IN_CLUSTER` | `false`; set true only for a verified local alias/IP |
| `MILVUS_ASSOCIATE_CLIENT_SPANS` | `false`; opt in after verifying Service ownership |
| `MILVUS_CLIENT_PORT` | `19530`; exact database client port |

Discovery keeps ready pod-backed endpoints for that Service and port, with
`service.instance.id=k8s.pod.uid`, pod name, node, Kubernetes namespace and cluster.
Resources retain logical service name/namespace, `db.system`, `db.system.name` and
`suse.ai.product`; datapoints retain `service_name`, `service_namespace`,
`db_system` and `suse_ai_product`. Get/list/watch access to Services, Endpoints
and Pods is required. Remove a local metrics endpoint override to use discovery.

Static fallback preserves external target overrides and never invents pod/node
identity. It adds the Collector's cluster and namespace only for the exact
configured Service FQDN/metrics port or an explicitly verified local target.
External endpoints stay unclustered. The endpoint remains the static instance ID.

With association enabled, CLIENT spans must match `milvus`, the exact
`<MILVUS_K8S_SERVICE_NAME>.<MILVUS_NAMESPACE>.svc.<K8S_CLUSTER_DOMAIN>` and
`MILVUS_CLIENT_PORT`, with caller cluster equal to `K8S_CLUSTER_NAME`.
The profile sets all three empty `suse.ai.peer.*` identity fields together.
Short names, IPs, cross-cluster callers, other domains, wrong/missing ports and
existing peer identities are not resolved. The default-off setting prevents
incorrect joins when a profile is configured for an external database.

Verify the native service's Cluster column, one instance per discovered pod UID
and the caller-to-native-service edge. A prior observed dependency expires
15 minutes after its last unresolved call. See [configuration and example](../README.md#associate-database-client-spans-with-the-native-service).

Milvus metrics use 9091; database calls use 19530. Optional server Jaeger tracing remains independent of the CLIENT association.
