# Collector 0.165.0 publication — 2026-11-11

The user authorized the T2 publication for SUSE AI Observability 3.0.0.
After `git fetch origin --prune --tags`, `origin/main` was
`b16fec5166653a01558c851300c011221e7af754`, the merge of
[PR #40](https://github.com/SUSE/suse-ai-opentelemetry-collector/pull/40).
Its tree, `c2d92798d984ff5a4fd711c1294634ff044862fc`, exactly matches validated
candidate `25dd6f8ab0cf1e7328eb0f568b9db63e90788bac`. All 35 source hashes in
the November 10 `validation-inputs.json` also match. PR #40's Collector
validation and both CodeQL checks passed before its November 10 merge.

The tag, release and GHCR version were absent at preflight.
[Release v0.165.0](https://github.com/SUSE/suse-ai-opentelemetry-collector/releases/tag/v0.165.0)
was published at **20:04:06 UTC** using
[the committed release notes](release-notes-0.165.0.txt). The remote tag points
to the merge commit above; the published notes are byte-identical to the file.

## Published image

[Release image workflow](https://github.com/SUSE/suse-ai-opentelemetry-collector/actions/runs/43093004631)
passed for linux/amd64, linux/arm64 and manifest publication from the tagged
commit. Its logs confirm nine successful in-image configuration validations
on each native architecture.

`ghcr.io/suse/suse-ai-opentelemetry-collector:0.165.0`

| Artifact | Digest |
| --- | --- |
| OCI index | `sha256:c7dcc629587d7c41bd32c5469ba541fde516bbc30f5295aca4b11120d526cdac` |
| linux/amd64 | `sha256:dbd6e50fa3b10db69da66781febb8422fee7ca64c351b4228c55cf55a79c4715` |
| linux/arm64 | `sha256:4a613a898ae9b20a67e5586b6f8cba6d55daae34ee980f9dd2f295c8e06b238a` |

Downloaded the complete image anonymously from GHCR using the immutable index
reference and `skopeo copy --all --preserve-digests`. The registry index and all
35 downloaded manifest, configuration and layer blobs passed SHA-256 checks.
Both image configurations specify UID `10001`, and both executable binaries
report `suse-ai-opentelemetry-collector version 0.165.0` with Go `1.26.10`.
Local arm64 execution used QEMU on the amd64 workstation.

All nine bundled `/otelcol/*.yaml` files are byte-identical to `v0.165.0` and
the validated candidate: `collector-config.yaml`, `milvus.yaml`, `qdrant.yaml`,
`opensearch.yaml`, `kubeflow.yaml`, `litellm-receiver.yaml`,
`litellm-receiver-no-auth.yaml`, `ollama-runtime.yaml` and `workload-probes.yaml`.
Both executable binaries are also byte-identical to the candidate:

| Binary | SHA-256 |
| --- | --- |
| amd64 | `80be4349d7492e5ffa257be929992fe7e7a32c8353c08d66ef1f69ff9e506025` |
| arm64 | `32f6a86bd5c6d6ec2a6a975a3ac352bf4faec8679286c6bc1e38c3bc9807f2ba` |

Inspection of every runtime layer found no temporary validation key or
ServiceAccount token; runtime environment metadata contains no build-only
validation variables. The November 10 candidate's **76 passing packaged
integration tests**, all **192 supported profile subsets**, and **375 ordered
validations and merged-config assertions per architecture** therefore cover
the published executables and configuration. Those integration suites were
not rerun for this publication; the byte comparisons establish equivalence.

## T3 image-mirror handoff

The verified source for the image-mirror lane is:

```text
ghcr.io/suse/suse-ai-opentelemetry-collector@sha256:c7dcc629587d7c41bd32c5469ba541fde516bbc30f5295aca4b11120d526cdac
```

Tag `0.165.0` resolves to that index. The
[machine-readable handoff](/home/thbertoldi/suse/qa/collector-0.165.0-publication-20261111-AMxKsB/t3-image-mirror-handoff.json)
also includes both platform digests and the release/workflow URLs. SUSE Registry
promotion remains the separate T3 lane, targeting
`registry.suse.com/ai/containers/suse/suse-ai-opentelemetry-collector:0.165.0`.

## Demo unavailable

The downstream demo at
`/home/thbertoldi/suse/qa/v3-live-20261110-y2y4dtt_` was not reachable.
Using its `kubeconfig-suse-ai`, Kubernetes API discovery timed out; a separate
bounded `kubectl --request-timeout=12s get --raw=/readyz` failed with
`Unable to connect to the server: context deadline exceeded`.

The rollout was skipped as authorized. No cluster mutations or changes to
`collector-values.yaml` were made. The existing profiles, environment,
credentials and CA settings were preserved; no rollback was performed.
Live readiness, fresh scrapes and `sts topology-sync list`/`describe` are not
claimed for this publication. On recovery, snapshot the then-current release
and reconcile its settings before pinning the published digest; do not restore
an older saved deployment or values file.

## Evidence

Publication evidence is retained in
`/home/thbertoldi/suse/qa/collector-0.165.0-publication-20261111-AMxKsB`:

- [Source/tree comparison](/home/thbertoldi/suse/qa/collector-0.165.0-publication-20261111-AMxKsB/source-preflight.json)
  and [PR #40 checks](/home/thbertoldi/suse/qa/collector-0.165.0-publication-20261111-AMxKsB/pr40.json).
- [Release/tag verification](/home/thbertoldi/suse/qa/collector-0.165.0-publication-20261111-AMxKsB/release-verification.json)
  and the original release notes, preflight responses and tag push log.
- [Published image inspection](/home/thbertoldi/suse/qa/collector-0.165.0-publication-20261111-AMxKsB/published-inspection.json),
  the downloaded OCI layout, registry index, inspection script and extracted
  binaries/profiles with their hashes and Go build information.
- [Completed workflow](/home/thbertoldi/suse/qa/collector-0.165.0-publication-20261111-AMxKsB/release-workflow.json),
  [CI build log](/home/thbertoldi/suse/qa/collector-0.165.0-publication-20261111-AMxKsB/release-image-build.log)
  and [18 completed in-image validations](/home/thbertoldi/suse/qa/collector-0.165.0-publication-20261111-AMxKsB/ci-profile-validations.json).
- [Demo reachability and skipped rollout](/home/thbertoldi/suse/qa/collector-0.165.0-publication-20261111-AMxKsB/demo-status.json).

The [candidate validation report](validation-0.165.0-2026-11-10.md) and
`/home/thbertoldi/suse/qa/collector-0.165.0-20261110` retain the November 10
packaged integration and profile-composition results.
