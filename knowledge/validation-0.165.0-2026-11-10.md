# Collector 0.165.0 release preparation — 2026-11-10

## Source and scope

The candidate continues [PR #40](https://github.com/SUSE/suse-ai-opentelemetry-collector/pull/40)
at `cb3a0ecd89cb4298821a0561e340bfc7b4b78897`, the upstream 0.165.0 update.
Implementation commit `82a2772` adds the Kubeflow bundle, documentation and
tests on local branch `release/collector-0.165.0`. Commit `5ce2d22` adds
optional bounded concurrency to the profile test runner, preserving its
assertions and default single-worker mode. Runtime build inputs are unchanged
by that follow-up. The candidate descends from current
main `5174c87`; the merge is conflict-free and produces the candidate tree.
The original checkout and its untracked files were preserved.

The profile was recovered from the saved demo configuration under
`/home/thbertoldi/suse/qa/demo-rebuild-20261109-d5tmgw2a`, also copied to
`saved-demo-kubeflow.yaml` in the evidence directory below. After normalizing
the receiver/pipeline names from `kubeflow_demo` to `kubeflow`, the only
configuration differences are environment-variable overrides for namespaces,
token path, certificate verification, and an optional trusted CA file.
The four jobs, selectors, ports, intervals, resource processors and exporter
are preserved. This is a saved-configuration comparison, not a fresh live read.

See [the Kubeflow guide](kubeflow.md) for the controller ServiceAccount token,
pod discovery permissions, `GET /metrics` ClusterRole/ClusterRoleBinding and
verified TLS configuration. The demo-compatible default still disables
controller certificate verification. No provider or database identity is
invented for Kubeflow controllers.

## Packaged images

Both architectures built from the checked-in Containerfile. Each passed nine
in-image configuration validations as UID `10001`. The build-only token was
bind-mounted, not copied into the image. Inspection of every image layer found
neither the fixture key nor a ServiceAccount token; the runtime environment
contains none of the build-only validation variables.

These are **local, unpublished platform manifests**, not GHCR release digests:

| Architecture | Manifest digest |
| --- | --- |
| linux/amd64 | `sha256:a84e3ae1cff84098dbda5a3aeeaf349b1f9d3bafbcda92c0d23455a1754544e4` |
| linux/arm64 | `sha256:7d8c0b8fe0949ffd8dfd8d85d82f2387ca59cbb06007fe7d8f921f4a17d7860c` |

Both extracted executables report
`suse-ai-opentelemetry-collector version 0.165.0` and Go `1.26.10`.
Their nine bundled YAML files are byte-identical to the committed sources:
`collector-config.yaml`, `litellm-receiver.yaml`,
`litellm-receiver-no-auth.yaml`, `milvus.yaml`, `qdrant.yaml`,
`opensearch.yaml`, `kubeflow.yaml`, `ollama-runtime.yaml` and
`workload-probes.yaml`. The runtime image user is `10001` on both platforms.
Arm64 executable checks run through QEMU on this amd64 workstation; native
arm64 hardware is not part of this local verification.

## Validation

All **76 packaged integration tests passed**, 38 per architecture. Tests use the
executable and YAML files extracted from each image, with local API/metrics fixtures replacing
deployment-specific endpoints. The LiteLLM authentication suite runs real
SUSE LiteLLM 1.81.13 containers.

| Suite | amd64 | arm64 (QEMU) |
| --- | --- | --- |
| Collector telemetry and identity | 14 passed | 14 passed |
| Database profiles | 10 passed | 10 passed |
| Kubeflow/KServe | 5 passed | 5 passed |
| Workload collection | 3 passed | 3 passed |
| Real LiteLLM authentication | 3 passed | 3 passed |
| Profile composition and empty discovery | 3 passed | 3 passed |

Both architectures passed all 192 supported profile subsets, 375 ordered
`validate` calls and 375 `print-config` assertions. All pipelines, receivers,
extensions, optional database peer hooks and LiteLLM authentication modes
were checked. The Kubeflow tests cover all four jobs, two model pods,
namespace/label/port/phase exclusions, service and pod/node identity, native
histograms, verified and self-signed TLS, wrong/missing tokens and empty discovery.

Composition checks use `--validation-workers 4` for this release verification.
Each worker runs the actual Collector's `validate` and `print-config`; all
merged-configuration assertions remain in the main test thread. The normal
single-worker execution is retained for CI and other callers.

The topology exporter's race tests passed both in its standalone module and
with the Collector dependency graph before the interruption. Those Go inputs
are unchanged. `go vet`, ShellCheck, actionlint, Python compilation and
`git diff --check` also passed. Three command/RBAC YAML examples parsed.

Evidence is retained at
`/home/thbertoldi/suse/qa/collector-0.165.0-20261110`:

- `image-build-{amd64,arm64}.log` and the two `.oci.tar` archives.
- `candidate-manifest-{amd64,arm64}.json`: image digests, versions, UID,
  executable hashes and every bundled configuration hash.
- `{amd64,arm64}-packaged-results.json` and per-suite logs/artifacts.
- `validation-summary.json` and `validation-output.txt`: consolidated totals.
- `validation-inputs.json`: source hashes and implementation commit.
- `saved-profile-comparison.txt`: exact differences from the saved demo.
- `exporter-race.log`, `collector-graph-race.log`, `exporter-vet.log`.

PR and CI evidence is recorded alongside these results after pushing the
candidate to `update-collector` for review.

## Remaining release and live work

The user confirmed that the live environment is down. Live access attempts
were stopped. No live ConfigMap comparison, deployment change or new
`sts topology-sync list`/`describe` verification is claimed for this candidate.

1. Review and merge PR #40 after the packaged checks and CI pass.
2. Publish GitHub release `v0.165.0` from the merged commit using
   [the release notes](release-notes-0.165.0.txt). The release workflow publishes
   `ghcr.io/suse/suse-ai-opentelemetry-collector:0.165.0`.
3. Record the published index and platform digests, inspect both downloaded
   architectures, and verify version, UID and all nine configurations against
   the candidate. Do not substitute the local digests above for release digests.
4. Once the demo is available, snapshot its current Collector deployment and
   configuration, compare the live Kubeflow overlay, then pin the Collector to
   the published digest. Replace the old Kubeflow overlay with the bundled
   profile while retaining its other profiles, environment, credentials, TLS
   mounts, RBAC and deployment settings. Keep a rollback patch.
5. Verify readiness, fresh scrapes, resource identity and backend topology
   synchronization; record the actual results and any existing backend errors.

SUSE Registry promotion through image-mirror is separate. Its intended target
is `registry.suse.com/ai/containers/suse/suse-ai-opentelemetry-collector:0.165.0`.
