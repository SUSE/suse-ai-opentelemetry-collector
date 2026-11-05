# Monitoring OpenSearch in SUSE AI

Load `/otelcol/opensearch.yaml` after the base Collector configuration. It uses
the Elasticsearch receiver for aggregate cluster/node statistics, not per-pod
scraping. The independent workload profile can probe individual OpenSearch pods.

| Variable | Default |
| --- | --- |
| `ELASTICSEARCH_NAMESPACE` | `SUSE_AI_NAMESPACE`, default `suse-private-ai` |
| `ELASTICSEARCH_K8S_SERVICE_NAME` | `opensearch-cluster-master-headless` |
| `ELASTICSEARCH_PORT` | `9200` |
| `ELASTICSEARCH_ENDPOINT` | `http://<Service>.<namespace>.svc.<K8S_CLUSTER_DOMAIN>:<port>` |
| `ELASTICSEARCH_SERVICE_NAME` | `opensearch` |
| `ELASTICSEARCH_SYSTEM` | `opensearch`; use `elasticsearch` for Elasticsearch |
| `ELASTICSEARCH_USERNAME` | `admin` |
| `ELASTICSEARCH_PASSWORD` | Supply from a Secret for secured clusters |
| `ELASTICSEARCH_TARGET_IN_CLUSTER` | `false`; ownership assertion for a local alias/IP |
| `ELASTICSEARCH_ASSOCIATE_CLIENT_SPANS` | `false`; explicit same-cluster Service association |
| `ELASTICSEARCH_CLIENT_PORT` | `ELASTICSEARCH_PORT` |

Set `K8S_CLUSTER_NAME` to the actual Collector cluster. In 0.164.1 the exact local
Service HTTP or HTTPS URL receives that cluster and Kubernetes namespace, even
without pod metadata. Other URLs require `ELASTICSEARCH_TARGET_IN_CLUSTER=true`
after verifying ownership; external endpoints remain unclustered. Existing
identity is preserved. Aggregate metrics never receive a fabricated pod UID.
The default cluster DNS domain is `cluster.local`; set `K8S_CLUSTER_DOMAIN` for
another domain. TLS verification remains enabled.

The optional CLIENT association matches only this Service's full DNS name,
configured client port, DB system and caller cluster. It fills three empty peer
fields with the same service name/namespace as the metrics and the local cluster.
It does not resolve short names, IPs or cross-cluster destinations. It stays off
by default because profiles may describe external targets or custom service
identities. External aggregate endpoints also prevent association unless
explicitly asserted local. Caller attributes and existing peers are preserved.

Check aggregate metrics and the Cluster column without expecting pod instances.
Generate a database call to verify the native-service edge. An old unresolved
dependency expires 15 minutes after its last unresolved call. See the
[environment-only example](../README.md#associate-database-client-spans-with-the-native-service).
