# Collector 0.164.1 publication — 2026-11-05

The user authorized publication after reviewing the candidate. [PR #41](https://github.com/SUSE/suse-ai-opentelemetry-collector/pull/41) merged as `cdb9ed07bdb8ef1250a07dbf99ce34c845750fd0` after Collector validation and both CodeQL checks passed. The merge tree equals tested candidate `0b211ca70962fdcc6f0c3c92b8940cac29dace43`.

[Release v0.164.1](https://github.com/SUSE/suse-ai-opentelemetry-collector/releases/tag/v0.164.1) was published at 18:06:16 UTC. Its tag points to that merge commit. The notes explain discovery/static mode selection, the migration from local endpoint overrides, cluster scope, required RBAC and the exact client association opt-in.

## Published image

[Release image workflow](https://github.com/SUSE/suse-ai-opentelemetry-collector/actions/runs/42081025891) passed for linux/amd64, linux/arm64 and manifest publication.

`ghcr.io/suse/suse-ai-opentelemetry-collector:0.164.1`

| Artifact | Digest |
| --- | --- |
| OCI index | `sha256:7bb0b0a6128fdc2659c72acf7b26c9acac56b51685610806ef3b8683cb2c7744` |
| linux/amd64 | `sha256:740fe68e5a2b4c3ef45723f3ef7a614f6d31bfbb18e7ffe7e496680e59ed1d5c` |
| linux/arm64 | `sha256:6bb0a94bba3318f2d06d1f03aba049dc798508b8a342195a71256915b26b60ce` |

Downloaded the image by its immutable index digest and verified the registry manifest hash. Both executable binaries and all eight bundled configuration files are byte-identical to the tested candidate. Both binaries report 0.164.1 and Go 1.26.10; both images use UID 10001. Runtime layers contain no temporary validation key or build-only placeholder environment variables. The candidate's 66 packaged Python tests, all 96 profile subsets and 184 ordered validations/assertions per architecture therefore cover the published code and configuration. CI also passed eight in-image configuration validations per architecture.

[Published inspection](/home/thbertoldi/suse/qa/collector-0.164.1-publication-20261105-Yummc1/published-inspection.json), [CI build log](/home/thbertoldi/suse/qa/collector-0.164.1-publication-20261105-Yummc1/release-image-build.log), [complete candidate validation](validation-0.164.1-2026-11-05.md).

## Demo on the released image

The `observability/opentelemetry-collector` Deployment now uses the GHCR release pinned to the index above, with the four bundled configuration paths (base, Milvus, Ollama runtime and workload probes). The temporary candidate volume and mount are removed. `MILVUS_ASSOCIATE_CLIENT_SPANS=true` remains enabled and the old local static endpoint override remains removed. TLS/backend settings are preserved. The unused candidate ConfigMap is retained for rollback. This is a direct Deployment patch; a later Helm upgrade must retain these settings.

At 18:17:13 UTC, the new Collector pod was Ready with zero restarts and reported version 0.164.1. Its runtime image ID matches the published index. Fresh scrape data with `otel_scope_version=0.164.1` has `up=1`, `k8s_cluster_name=suse-ai`, and both `service_instance_id` and `k8s_pod_uid` equal the actual Milvus pod UID `63009ba2-99ab-4481-9cb4-24eee6c0ab36`.

Native Milvus service `112869539086775` has `cluster-name:suse-ai`; instance `186235368201850` identifies that pod. RAG service `267074156912894` connects to native Milvus via edge `126525909538009`. A fresh post-rollout CLIENT span contains the expected service name, namespace and cluster peer attributes. Old observed dependency `240022781540498` and edge `114212019677228` remain absent. The earlier candidate check recorded their expiry after the last unresolved call; no new 15-minute wait was required for this image rollout.

`sts topology-sync list` and `describe` were repeated at 18:17:18 UTC. Agent and Kubernetes - suse-ai are Running, with the same historical error counts (79/34) and 10 active details each. These pre-existing missing-target/duplicate-identity errors are outside this profile change. The release Collector log contains no error-level entries. The demo has one Milvus pod; two-pod behavior for Milvus and Qdrant is covered by discovery fixtures.

[Live assertions](/home/thbertoldi/suse/qa/collector-0.164.1-publication-20261105-Yummc1/live-release-checks.json), [post-rollout span](/home/thbertoldi/suse/qa/collector-0.164.1-publication-20261105-Yummc1/live-release-span-evidence.json), [runtime image](/home/thbertoldi/suse/qa/collector-0.164.1-publication-20261105-Yummc1/live-release-pod-evidence.json), [synchronizations](/home/thbertoldi/suse/qa/collector-0.164.1-publication-20261105-Yummc1/live-release-sync-summary.json).

Rollback to the previous working candidate overlay is saved in `deployment-release-rollback.json` in the publication evidence directory. The original 0.164.0 rollback in the candidate evidence directory now explicitly restores the original image and uses Kubernetes' required `mountPath` merge key. Both rollback patches passed server dry-run validation. Deployment backups remain private.

## SUSE Registry and monitoring guide

[Image-mirror MR !498](https://gitlab.suse.de/suse-ai/image-mirror/-/merge_requests/498) adds only tag 0.164.1 to the existing Collector stanza, retaining previous tags and `containers/suse/suse-ai-opentelemetry-collector`. Tools were rebuilt and generated configuration compared with clean staging: exactly one new source/target mapping, no removed or changed existing mappings.

The MR is submitted to staging. SUSE Registry publication still requires the normal merge, staging scans/signing and production promotion. No pipeline settings were bypassed. This environment has GitLab SSH push access but no authenticated GitLab API/browser session for merging the MR; production promotion is not claimed. The demo uses the verified GHCR release while that process is pending.

The monitoring guide's product-topic changes remain on local branch `docs/database-profile-identity-0.164.1` in `doc-suse-ai`, preserving existing user drafts. The incremental [guide patch](/home/thbertoldi/suse/qa/collector-0.164.1-20261105/monitoring-guide.patch) and successful HTML/DocBook/YAML validation are unchanged. Its SUSE Registry publication marker remains appropriate until mirror promotion finishes.
