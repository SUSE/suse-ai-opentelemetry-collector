# Monitoring Kubeflow and KServe

Collector 0.165.0 bundles the demo's pod scrape profile at
`/otelcol/kubeflow.yaml`. Load it after `/otelcol/collector-config.yaml` and keep
the other profiles you already use. It adds its own `prometheus/kubeflow`
receiver and `metrics/kubeflow` pipeline; it does not replace the base scrape
list. Remove an older Kubeflow overlay when enabling this profile to avoid
collecting the same metrics twice.

```yaml
command:
  name: otelcol/otelcol-custom
  extraArgs:
    - --config=/otelcol/collector-config.yaml
    - --config=/otelcol/kubeflow.yaml
```

| Job | Namespace | Pod label | Port / protocol | Service identity |
| --- | --- | --- | --- | --- |
| Pipelines API | `KUBEFLOW_NAMESPACE` | `app=ml-pipeline` | 8888 / HTTP | `kubeflow-pipelines` |
| Workflow Controller | `KUBEFLOW_NAMESPACE` | `app=workflow-controller` | 9090 / HTTPS | `kubeflow-workflow-controller` |
| KServe Controller | `KUBEFLOW_NAMESPACE` | `control-plane=kserve-controller-manager` | 8443 / HTTPS | `kserve-controller` |
| KServe model pods | `KSERVE_NAMESPACE` | nonempty `serving.kserve.io/inferenceservice` | 8080 / HTTP | The InferenceService label value |

All jobs select Running pods, scrape `/metrics` every 30 seconds with a 10-second
timeout, and preserve native metric names and histogram buckets. The resource
carries `service.name`, the actual namespace, `service.instance.id=k8s.pod.uid`,
pod name, node, cluster and `suse.ai.product`. Datapoints retain `service_name`
and `service_namespace`. Pipelines and Workflow Controller use product
`kubeflow-pipelines`; the KServe jobs use `kserve`. No GenAI provider or database
system is invented for these controllers. These standard OTel Resource Metrics
use the base OTLP exporter, including `up` for target availability. The receiving
SUSE Observability Collector supplies resource topology to
`sts_topo_opentelemetry_collector`.

| Variable | Default / purpose |
| --- | --- |
| `KUBEFLOW_NAMESPACE` | `kubeflow`; controller namespace |
| `KSERVE_NAMESPACE` | `kubeflow-user-example-com`; model pod namespace |
| `K8S_CLUSTER_NAME` | Base configuration setting; supply the actual cluster name |
| `KUBEFLOW_METRICS_TOKEN_FILE` | `/var/run/secrets/kubernetes.io/serviceaccount/token`; readable bearer token for both HTTPS controllers |
| `KUBEFLOW_METRICS_INSECURE_SKIP_VERIFY` | `true`, matching the demo's self-signed controller certificates |
| `KUBEFLOW_METRICS_CA_FILE` | Empty; optional trusted CA bundle for both HTTPS controllers |

The controller HTTPS defaults retain the demo's certificate behavior: they send
a bearer token without checking the server certificate. For verified TLS, mount
a CA bundle, set `KUBEFLOW_METRICS_CA_FILE` to its path and set
`KUBEFLOW_METRICS_INSECURE_SKIP_VERIFY=false`. The certificates must cover the
discovered pod IPs. Deployments needing different TLS policies or selectors per
controller can mount a customized copy of the profile.

Both protected scrapes use the Collector's ServiceAccount bearer token. Ensure
the projected token is mounted and readable by UID 10001. A missing token file
fails configuration validation even when no controller pods exist. For local
validation, point `KUBEFLOW_METRICS_TOKEN_FILE` at a nonsecret fixture; do not ship
that fixture as a runtime credential.

## RBAC

Keep the base configuration's metadata enrichment permissions documented in the
[README](../README.md#running). Pod discovery additionally needs `get`, `list`
and `watch` on Pods in both configured namespaces. If the existing Collector
ClusterRole already grants these, no additional discovery rule is needed.

The protected Workflow Controller and KServe Controller endpoints delegate
authorization to Kubernetes. Grant the Collector ServiceAccount **GET on the
non-resource URL `/metrics`** through a ClusterRole and ClusterRoleBinding.
[Kubernetes non-resource permissions](https://kubernetes.io/docs/reference/access-authn-authz/rbac/)
require this cluster-scoped binding. The Collector does not
need permission to create TokenReviews or SubjectAccessReviews; those checks
are performed by the controller endpoints.

```yaml
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: suse-ai-kubeflow-metrics-reader
rules:
  - nonResourceURLs: ["/metrics"]
    verbs: [get]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: suse-ai-kubeflow-metrics-reader
roleRef:
  apiGroup: rbac.authorization.k8s.io
  kind: ClusterRole
  name: suse-ai-kubeflow-metrics-reader
subjects:
  - kind: ServiceAccount
    name: opentelemetry-collector
    namespace: observability
```

Replace the subject with the ServiceAccount actually used by your Collector.
Check its effective permissions using an identity allowed to impersonate it:

```sh
kubectl auth can-i get /metrics --as=system:serviceaccount:observability:opentelemetry-collector
kubectl auth can-i list pods -n kubeflow --as=system:serviceaccount:observability:opentelemetry-collector
kubectl auth can-i watch pods -n kubeflow-user-example-com --as=system:serviceaccount:observability:opentelemetry-collector
```

Allow network access from the Collector to the Kubernetes API and the four
scrape ports. This profile does not collect Model Registry metrics or establish
workflow/model relationships by itself; those still require their own telemetry.

## Validation

`tests/test_kubeflow.py` runs the actual Collector against a Kubernetes list/watch
fixture and HTTP/HTTPS metrics servers. It covers all four jobs, two model pods,
namespace/label/phase/port exclusions, resource and datapoint identity, histogram
buckets, default self-signed TLS, verified TLS, custom namespaces, wrong/missing
tokens, and empty discovery. `tests/test_profiles.py` includes this profile in all
192 supported combinations and checks both optional-profile orders where distinct.
