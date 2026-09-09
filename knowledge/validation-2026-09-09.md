# Collector fixes and validation, 2026-09-09

The user authorized corrections after [the baseline audit](audit-2026-09-09.md), then requested a PR and review of outstanding PRs. These results describe `fix/collector-v0.160.0-release` on top of `5051b297812af3fb54c8503f016fa25d6cd72750`, the fetched `origin/main`. No image was published or deployment changed. The original configuration remains recoverable from the audit's named backup stash; `pin.sh`, `.last_session`, historical stashes, and the existing worktree were preserved.

## Corrections

| Audit findings | Implemented behavior |
| --- | --- |
| 1: incompatible container toolchain | Use Go 1.26.7 for builder v0.160.0; validate configuration during image construction. |
| 2: invalid draft configuration | Replace the draft's unsupported topology configuration with standard OTLP pipelines. Retain health checks, Jaeger, configurable endpoints, and compatibility mappings. |
| 3–4: dropped and duplicated traces | Export each original span once, including spans without Kubernetes metadata. Preserve IDs, service identity, and peer attributes. |
| 5: destructive resource promotion | Fill missing attributes, preserve source host/namespace/provider, and append distinct CSV model names within each resource batch. |
| 6: API key in topology failure logs | Mask configuration keys, encode request query values, and unwrap transport errors without the credential-bearing URL. |
| 7: missing infrastructure context | Promote scraper identity to standard service, namespace, GenAI/DB, and hardware resource attributes; retain distinct target instances. |
| 8: duplicated usage measurements | Use one original-metric export path with normalization. Span metrics retain their separate `otel_span.*` names. |
| 9: unbounded topology requests/shutdown | Add a positive timeout, request cancellation, coordinated final flush, and redirect rejection. |
| 10: publication/update gaps | Cover configuration and exporter changes, add runtime CI, fetch matching release manifests, and build/test updates before creating their PR. |

The custom topology exporter remains available for existing deployments that explicitly enable it. The default configuration sends standard OTLP resources. Delivery to `sts_topo_opentelemetry_collector` is the receiving SUSE Observability collector's responsibility.

## Verification

| Check | Result |
| --- | --- |
| Build checked-in collector with `go build -mod=readonly` | Passed with Go 1.27.1; generated module files unchanged |
| Build final Containerfile | Passed on linux/amd64 with Go 1.26.7 |
| Validate bundled configuration in final image | Passed as user 10001; packaged YAML matches the working file byte for byte |
| Seven integration cases in `tests/test_collector.py` | Passed against both the regenerated collector and the binary extracted from the versioned release candidate |
| Exporter race tests | Passed in the exporter module, the checked-in collector graph, and an isolated regenerated collector graph |
| Exporter `go vet ./...` | Passed |
| Packaged exporter connection-error probe | Passed: synthetic API key absent from failure logs; process shut down within the probe's bound |
| Run updater with explicit `v0.160.0` in an isolated checkout | Passed: regenerate, build, and validate; builder manifest matches the working manifest |
| ShellCheck, actionlint, and `git diff --check` | Passed |
| Live `sts topology-sync list -o json` | Unavailable: `http://localhost:8081/api` refused the connection |

The integration cases cover Elasticsearch resource processing, log identity, metric normalization and canonical precedence, scraper resource identity and histograms, legacy span normalization, and original trace identity/model aggregation. Fixtures replace external exporters with local files, Kubernetes discovery with local discovery files, Kubernetes enrichment with passthrough, and Elasticsearch API input with OTLP. They exercise the actual collector's processor chains and Prometheus scraping. They do not verify real deployment credentials, RBAC, Elasticsearch API compatibility, or backend topology delivery.

The final local image is `suse-ai-otelcol:0.160.0-candidate`, image ID `sha256:6c80f416ccb7db66f5c372d9a86f5a39aee6f5923f12eea61db309110311440c`. Its bundled configuration validates as user 10001, and `--version` reports `0.160.0`. The Go build image manifest offers amd64 and arm64 variants; only the amd64 collector image was built in this session. The updated GitHub workflows were linted and their relevant commands exercised locally. Remote validation status is reported on the pull request.

## Dependency scan

`govulncheck` v1.8.0 on the updated unstripped binary reports zero affected symbols or imported packages and five module-level advisories: GO-2026-6355, GO-2026-6354, GO-2026-5932, GO-2022-0646, and GO-2022-0635. They concern SSH/OpenPGP in `golang.org/x/crypto` v0.55.0 and S3 crypto in `github.com/aws/aws-sdk-go` v1.55.8. The collector's `go list -deps` output contains none of those affected package families.

The OCB-built image binary has no symbol section. The scanner's v1.8.0 implementation falls back to module-level precision for stripped binaries and reports known vulnerable symbols from those modules without establishing their presence in the executable (`internal/vulncheck/binary.go`, lines 107–111). This explains the packaged scan's five apparent symbol findings. The scans preceded the version-metadata correction; the audit binaries and versioned release candidate contain exactly the same 509 dependency module versions. These remain dependency maintenance advisories, not demonstrated reachable vulnerabilities; this was not an operating-system image scan.

## PR review and release preparation

GitHub returned zero open PRs before creating the release-preparation PR. The relevant changes had already been resolved:

| PR | Review result |
| --- | --- |
| [#25](https://github.com/SUSE/suse-ai-opentelemetry-collector/pull/25) | Configuration update already merged; the corrections above address its remaining resource-identity defects. |
| [#28](https://github.com/SUSE/suse-ai-opentelemetry-collector/pull/28) | Collector v0.160.0 update already merged; its component and dependency changes remain included. |
| [#31](https://github.com/SUSE/suse-ai-opentelemetry-collector/pull/31) | Exporter gRPC v1.83.1 update already merged and covered by the exporter tests. |
| [#32](https://github.com/SUSE/suse-ai-opentelemetry-collector/pull/32) | Dependabot already closed the generated-collector gRPC v1.83.1 proposal; the module now selects v1.83.2. Applying it would downgrade the dependency. |
| [#33](https://github.com/SUSE/suse-ai-opentelemetry-collector/pull/33) | Dependabot already closed the Thrift v0.24.0 proposal; that version is present in the generated collector. |

No additional PR closure or cherry-pick was needed. Upstream's latest release is [v0.160.0](https://github.com/open-telemetry/opentelemetry-collector-releases/releases/tag/v0.160.0), checked on 2026-09-09; this repository's latest release is v0.156.0. The intended next tag, v0.160.0, does not yet exist.

Release preparation also found an empty distribution version in the generated executable, which made `--version` fail. The manifest now sets `0.160.0`; the updater embeds the selected tag's version and regenerates the entry point. Regeneration changed no dependency files. All seven integration cases, including a new binary-versus-manifest version check, pass against both the regenerated executable and the binary extracted from the release candidate image.

After merge and successful checks, publishing a GitHub release for the new tag v0.160.0 triggers the existing container publication workflow. It builds amd64 and arm64 and publishes the combined manifest with `0.160.0` and `0.160` image tags. Merely pushing a Git tag does not trigger the current release workflow.

## Evidence and remaining deployment check

Session artifacts are in `/tmp/suse-otel-fixes-20260909/`: final container build and integration logs, the extracted binary and configuration, the isolated updater run, the redaction probe, dependency comparisons, both vulnerability reports, and the failed live synchronization response. The tests and repeatable commands are retained in the repository and [README](../README.md); temporary artifacts are session-local.

A connected deployment still needs scrape-target and RBAC verification, then `sts topology-sync list` and `sts topology-sync describe` against the intended backend. Local validation does not establish production health or topic delivery.
