# Collector 0.164.1 database identity verification

Prepared on `fix/database-identity-0.164.1` from `c9dae09` (main/v0.164.0).
This report records the completed preparation and validation before publication.
The user subsequently authorized pushing and releasing 0.164.1. Pre-existing
untracked files were preserved.

## Changes

- Milvus/Qdrant profiles discover ready, pod-backed Endpoints for the configured
  Service, namespace and metrics port. Each pod UID becomes `service.instance.id`;
  pod name, node, Kubernetes namespace and cluster accompany the existing logical
  service, DB system and product attributes.
- A nonempty `*_METRICS_ENDPOINT` selects only the static job. Unset/empty selects
  discovery. External targets retain compatibility. Remove local overrides to
  enable per-pod scraping; the default does not fall back on a discovery error.
- Exact local Service endpoints and explicitly verified local aliases get the
  Collector's cluster on aggregate/static metrics. External targets do not inherit
  it. No aggregate/static processor invents a pod UID or node identity.
- Each loaded profile fills its own trace-processor hook, avoiding list replacement
  during configuration merging. `*_ASSOCIATE_CLIENT_SPANS=true` enables the exact
  Service FQDN/client-port/DB-system match with a reported same-cluster caller.
  Matching precedes local cluster inference. Short names, IPs, other/unknown
  clusters, wrong/missing ports and existing/partial peer identities are preserved
  unresolved. The opt-in prevents guessing ownership for external targets and
  custom logical identities. Metrics and peers use the same logical identity.
- Distribution version is 0.164.1; upstream core 0.164.0, contrib 0.164.1 and all
  dependency versions remain unchanged. Helm examples target the new release.

## Candidate image

Both platform builds succeeded, including eight in-image profile validations per
architecture as UID 10001. All eight YAML files match final source byte-for-byte.
Both binaries report 0.164.1 and Go 1.26.10. Temporary validation keys and build-only
placeholder environment variables are absent from the runtime artifacts.

Local, unpublished OCI index: `sha256:cd96e6506d084dcac75d7ad5bafa688c007e391e25aa0dfd6ed88fa0ddf477f9`.

[Image inspection](/home/thbertoldi/suse/qa/collector-0.164.1-20261105/candidate-manifest.json),
[final build log](/home/thbertoldi/suse/qa/collector-0.164.1-20261105/image-build-final.log),
[OCI archive](/home/thbertoldi/suse/qa/collector-0.164.1-20261105/collector-0.164.1-final.oci.tar).
The digest identifies this local candidate, not a published SUSE Registry image.

## Runtime validation

All 33 Python tests passed against the locally built binary and each final packaged
architecture (66 packaged tests total): 14 Collector tests (including the shared identity fixture), 10 new
database-profile tests, 3 profile-composition/empty-API tests, 3 workload tests and
3 real LiteLLM authentication tests. The new tests exercise actual Prometheus
Kubernetes discovery using a local API fixture, two pod targets, real scraping,
OTLP input, processor chains, Count observations and file export.

The matrix covers all 96 supported subsets and both profile orders where distinct:
184 `validate` calls and 184 `print-config` assertions. It checks preservation of
pipelines/receivers/extensions and each profile's association hook. Runtime checks
cover static/discovery exclusivity, local/external cluster attribution, numeric
and string ports, canonical/legacy DB attributes, same/different/unknown caller
clusters (including an unknown caller carrying a pod UID), existing partial peers,
custom environment settings and profiles absent/disabled.

Exporter race tests passed in both module graphs. ShellCheck, actionlint, Python
compilation and whitespace checks passed. The image's existing build-argument
warnings concern literal validation placeholders; the runtime image has none.

[amd64 packaged test output](/home/thbertoldi/suse/qa/collector-0.164.1-20261105/packaged-amd64-summary.log),
[arm64 packaged test output](/home/thbertoldi/suse/qa/collector-0.164.1-20261105/packaged-arm64-summary.log),
[profile validation log](/home/thbertoldi/suse/qa/collector-0.164.1-20261105/amd64-profiles/profile-validation.log),
[exporter race test](/home/thbertoldi/suse/qa/collector-0.164.1-20261105/test-exporter.log),
[Collector dependency graph race test](/home/thbertoldi/suse/qa/collector-0.164.1-20261105/test-exporter-collector-graph.log).

| Suite | Tests per architecture | amd64 | arm64 (QEMU) |
| --- | ---: | --- | --- |
| `test_collector.py` | 14 | PASS (20.110s) | PASS (29.809s) |
| `test_database_profiles.py` | 10 | PASS (28.227s) | PASS (56.416s) |
| `test_profiles.py` | 3 | PASS (107.523s) | PASS (972.833s) |
| `test_workload_collection.py` | 3 | PASS (7.901s) | PASS (14.132s) |
| `test_litellm_auth.py` | 3 | PASS (32.408s) | PASS (41.707s) |

Both architectures validated every supported profile combination. Arm64 ran
under QEMU, not on native hardware.

[Consolidated test output](/home/thbertoldi/suse/qa/collector-0.164.1-20261105/validation-output.txt).

## Live demo

Used the kubeconfigs documented in the demo's existing `REVIEW.txt`. The running
Collector image remains 0.164.0; it validated and runs the final candidate base and
Milvus configuration through ConfigMap `collector-database-identity-01641` in
`observability`. No image push was needed. The endpoint override was removed and
`MILVUS_ASSOCIATE_CLIENT_SPANS=true` enabled. The final ConfigMap was compared with
source byte-for-byte. The other selected profiles and existing TLS/backend settings
remain in use. The current overlay persists; a later Helm upgrade may replace it.

At 2026-11-05 17:18:29 UTC:

- Native Milvus service `112869539086775` has `cluster-name:suse-ai`.
- Instance `186235368201850` uses pod UID
  `63009ba2-99ab-4481-9cb4-24eee6c0ab36`, matching the Kubernetes API. Pod name:
  `milvus-standalone-59d545fc54-47z47`; node: `suse-ai-wkrgpu3`; namespace:
  `suse-private-ai`. Scrape `up=1`; current series have `k8s_cluster_name=suse-ai`.
- RAG service `267074156912894` calls native Milvus through edge
  `126525909538009`. Actual Milvus CLIENT spans carry all three peer attributes
  and `server.address=milvus.suse-private-ai.svc.cluster.local`, port 19530.
- Old observed dependency `240022781540498` and edge `114212019677228` are absent.
  Last captured unresolved span was 17:01:44 UTC. The old dependency was still
  present at 17:16:43 and gone at 17:18:29, consistent with the 15-minute expiry
  plus backend reconciliation. The old static native instance also expired.
- Final Collector logs contain no scrape/transform errors. Existing component
  alias and Kubernetes Endpoints deprecation warnings remain.

This is backend API, trace and Kubernetes evidence. The demo has one Milvus pod;
independent two-pod identity for both databases is covered by real discovery API
fixtures. Qdrant and OpenSearch were not deployed to the demo for this check.

`sts topology-sync list` and `describe` were run. Agent and Kubernetes - suse-ai
are Running but each reports 10 active error details (missing relation targets,
duplicate volume/container identities). These are recorded, not repaired by this
profile change; no globally clean-backend claim is made.

[Before topology](/home/thbertoldi/suse/qa/collector-0.164.1-20261105/live-before-topology.json),
[before metric](/home/thbertoldi/suse/qa/collector-0.164.1-20261105/live-before-up-corrected.json),
[final evidence](/home/thbertoldi/suse/qa/collector-0.164.1-20261105/live-final-summary.json),
[actual spans](/home/thbertoldi/suse/qa/collector-0.164.1-20261105/live-database-span-evidence.json),
[pod identity](/home/thbertoldi/suse/qa/collector-0.164.1-20261105/live-pod-identity.json),
[synchronizations](/home/thbertoldi/suse/qa/collector-0.164.1-20261105/live-sync-summary.json),
[Collector log](/home/thbertoldi/suse/qa/collector-0.164.1-20261105/live-collector-final.log).
Early exploratory metric queries used seconds; the corrected before/after files
above use the API's required milliseconds.

The original deployment backup is private in the evidence directory. A rollback
patch restores its previous arguments and endpoint variable and removes only this
candidate's volume and association flag:

```sh
kubectl --kubeconfig /home/thbertoldi/suse/qa/demo-native-stackpack-20261105-qOhD/kubeconfig-suse-ai \
  -n observability patch deployment opentelemetry-collector --type=strategic \
  --patch-file=/home/thbertoldi/suse/qa/collector-0.164.1-20261105/live-rollback.json
```

## Documentation

README and the Milvus, Qdrant and OpenSearch knowledge topics cover selectors,
mode selection, upgrade steps, RBAC, cluster scope, exact association and expiry.
[Release notes](release-notes-0.164.1.txt) explain the behavior change.

The monitoring guide changes are on `docs/database-profile-identity-0.164.1` in
`/home/thbertoldi/suse/doc-suse-ai`. Existing draft edits were preserved. Updated:

- `tasks/AI-monitoring-native-products.adoc`: product settings, discovery/static
  selection, aggregate identity, exact client association, verification and expiry.
- `tasks/AI-monitoring-native-collector.adoc`: per-pod profile behavior.
- `references/AI-monitoring-integrations.adoc`: coverage and association reference.
- `articles/ai-monitoring.adoc`: candidate version and pending-publication marker.

[Incremental guide diff](/home/thbertoldi/suse/qa/collector-0.164.1-20261105/monitoring-guide.patch) excludes pre-existing
edits. Monitoring HTML and DocBook compile with no warnings; XML is well formed;
116 unique IDs, 38 internal references and 24 YAML blocks validate.
[Documentation validation](/home/thbertoldi/suse/qa/collector-0.164.1-20261105/docs-validation.json).

The legacy 2.x product instructions remain separate. The guide's publication
marker requires the 0.164.1 image to be available before these instructions ship.

## Publication boundary

The user confirmed publication after reviewing this report. Commit/review the
branch and publish through the existing workflow,
verify the published platform digests and profiles, and follow the normal SUSE
image-mirror process. Replace the temporary demo overlay with the approved image
through its deployment configuration. Remote publication results are recorded
separately from the preparation evidence above.
