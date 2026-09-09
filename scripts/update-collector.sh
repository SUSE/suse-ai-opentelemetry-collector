#!/usr/bin/env bash
set -euo pipefail

cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.."

# An explicit tag makes updates reproducible; without one, use the latest release.
COLLECTOR_TAG=${1:-$(curl -fsSL --retry 3 --connect-timeout 15 --max-time 60 \
  https://api.github.com/repos/open-telemetry/opentelemetry-collector-releases/releases/latest | jq -er .tag_name)}
if [[ ! "$COLLECTOR_TAG" =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]]; then
  echo "Expected a stable collector release tag, such as v0.160.0" >&2
  exit 1
fi

UPDATE_TMP=$(mktemp -d)
trap 'rm -rf -- "$UPDATE_TMP"' EXIT
MANIFEST_BASE="https://raw.githubusercontent.com/open-telemetry/opentelemetry-collector-releases/$COLLECTOR_TAG/distributions"
CONTRIB_MANIFEST="$UPDATE_TMP/contrib.yaml"
export CONTRIB_MANIFEST
export COLLECTOR_VERSION="${COLLECTOR_TAG#v}"

echo "Downloading manifests for $COLLECTOR_TAG..."
curl -fsSL --retry 3 --connect-timeout 15 --max-time 60 \
  "$MANIFEST_BASE/otelcol-k8s/manifest.yaml" -o "$UPDATE_TMP/builder.yaml"
curl -fsSL --retry 3 --connect-timeout 15 --max-time 60 \
  "$MANIFEST_BASE/otelcol-contrib/manifest.yaml" -o "$CONTRIB_MANIFEST"
yq -e '.receivers[] | select(.gomod | contains("/elasticsearchreceiver "))' "$CONTRIB_MANIFEST" >/dev/null

yq -i '
  .dist.name = "suse-ai-opentelemetry-collector" |
  .dist.description = "Minimal OTel Collector distribution for monitoring SUSE AI" |
  .dist.output_path = "./suse-ai-opentelemetry-collector" |
  .dist.version = strenv(COLLECTOR_VERSION) |
  del(.dist.module, .dist.build_tags) |
  .receivers += [load(strenv(CONTRIB_MANIFEST)).receivers[] | select(.gomod | contains("/elasticsearchreceiver "))] |
  .exporters += [{"gomod": "github.com/suse/suse-ai-opentelemetry-collector/topologyexporter v0.0.0", "path": "./topologyexporter"}]
' "$UPDATE_TMP/builder.yaml"

cp "$UPDATE_TMP/builder.yaml" builder-config.yaml
sed -i "s|builder@v[0-9.]*|builder@$COLLECTOR_TAG|g" Containerfile

go install "go.opentelemetry.io/collector/cmd/builder@$COLLECTOR_TAG"
"${GOBIN:-$(go env GOPATH)/bin}/builder" --config builder-config.yaml

# A newer builder can compile on an automatically downloaded Go toolchain while
# the container still uses an older, fixed toolchain. Catch that before a PR.
REQUIRED_GO=$(awk '/^go / {print $2; exit}' suse-ai-opentelemetry-collector/go.mod)
IMAGE_GO=$(sed -n 's|^FROM dp.apps.rancher.io/containers/go:\([0-9.]*\).*|\1|p' Containerfile)
if [[ -z "$IMAGE_GO" || "$(printf '%s\n' "$REQUIRED_GO" "$IMAGE_GO" | sort -V | head -n 1)" != "$REQUIRED_GO" ]]; then
  echo "Update the Containerfile Go image to at least $REQUIRED_GO before publishing $COLLECTOR_TAG" >&2
  exit 1
fi

API_KEY=validation ELASTICSEARCH_PASSWORD=validation \
  ./suse-ai-opentelemetry-collector/suse-ai-opentelemetry-collector validate --config collector-config.yaml
./suse-ai-opentelemetry-collector/suse-ai-opentelemetry-collector --version
echo "Collector $COLLECTOR_TAG built and configuration validated."
