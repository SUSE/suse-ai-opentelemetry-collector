# arm64 build for publish-container.yml

**Date:** 2026-06-02
**Branch:** `chore/arm64-build`

## Goal

Publish a multi-arch container manifest (`linux/amd64` + `linux/arm64`) from `.github/workflows/publish-container.yml`, replacing the current amd64-only build. Tag set, registry, triggers, and SHA-pinning conventions stay unchanged.

## Approach

Native matrix + digest merge. Two parallel build jobs (one per arch on its own native runner) push by digest, then a third job composes the manifest list with `docker buildx imagetools create`.

Rejected alternatives:
- **QEMU single-job** — arm64 Go builds under emulation are 10–20 min and occasionally flaky on multi-module Go projects. Chose against because this is a 30+ module OTel collector build.
- **Docker GitHub Builder reusable workflow** (`docker/github-builder/.github/workflows/build.yml`) — clean but limits control over the per-job step list, and the repo convention pins everything by commit SHA which is awkward for a reusable workflow ref.

## Workflow structure

### Job 1: `build` (matrix, parallel)

- `strategy.matrix.platform: [linux/amd64, linux/arm64]`, `fail-fast: false`
- `runs-on`: `ubuntu-24.04-arm` when `matrix.platform == linux/arm64`, else `ubuntu-latest`. Repo is public, so arm64 runner minutes are free.
- Steps:
  1. Checkout
  2. Login to `dp.apps.rancher.io` (needed to pull SUSE base images for both Containerfile stages)
  3. Login to `ghcr.io`
  4. `docker/setup-buildx-action` (no QEMU — every leg is native)
  5. `docker/metadata-action` — used only for `labels` here; tags get applied by the merge job
  6. `docker/build-push-action` with `outputs: type=image,name=ghcr.io/${{ github.repository }},push-by-digest=true,name-canonical=true,push=true` and `platforms: ${{ matrix.platform }}`
  7. Export digest to `/tmp/digests/<digest>` and `actions/upload-artifact` it as `digests-linux-amd64` / `digests-linux-arm64`

### Job 2: `merge` (single job, `needs: build`)

- `runs-on: ubuntu-latest`
- Steps:
  1. `actions/download-artifact` with `pattern: digests-*` and `merge-multiple: true`
  2. Login to `ghcr.io` (no Rancher login needed — merge job only writes to ghcr.io)
  3. `docker/setup-buildx-action`
  4. `docker/metadata-action` — same `tags:` config as today (semver, sha-short, latest-on-main)
  5. `docker buildx imagetools create` — composes the manifest list across both digests under each metadata tag, reading the tag set from `DOCKER_METADATA_OUTPUT_JSON`
  6. `docker buildx imagetools inspect` of the primary tag — prints the final manifest for verification in CI logs

## Things that stay the same

- Triggers: push to `main` with the existing paths filter, release `published`, `workflow_dispatch`
- Tag scheme: `type=semver,pattern={{version}}`, `{{major}}.{{minor}}`, `type=sha,format=short`, `type=raw,value=latest` on main
- Registry / image: `ghcr.io/${{ github.repository }}`
- Permissions: `contents: read`, `packages: write` per job
- SHA-pinning convention from commit `244e786` — every action pinned to its commit SHA with `# vN` trailing comment

## New actions added (pinned)

- `docker/setup-buildx-action` v4.1.0
- `actions/upload-artifact` v7.0.1
- `actions/download-artifact` v8.0.1

## Containerfile

No changes needed. Each matrix leg runs natively, so `FROM`s resolve to the matching-arch image from the multi-arch base, and Go compiles for the host arch by default. User confirmed SUSE base images (`dp.apps.rancher.io/containers/go:1.25.5`, `dp.apps.rancher.io/containers/bci-micro:15.7`) publish aarch64 variants.

## Risks

- If a future SUSE base image tag drops the arm64 variant, the arm64 matrix leg fails with a clear `no matching manifest for linux/arm64` error. Failure is loud and isolated; fix would be a different base tag, not a workflow change.
- Push-by-digest produces a brief window where digests are in the registry but no tags reference them. The merge job tags them within the same workflow run; the only externally visible window where the new tags don't exist is the time between the prior run finishing and this run's merge step completing — which matches current behavior.
