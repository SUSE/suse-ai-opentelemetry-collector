#!/bin/bash
set -e

# Get latest version from GitHub API
# We use the releases from opentelemetry-collector-releases as it's more direct for manifests
LATEST_TAG=$(curl -s https://api.github.com/repos/open-telemetry/opentelemetry-collector-releases/releases/latest | jq -r .tag_name)
VERSION_NO_V=${LATEST_TAG#v}

echo "Latest version found: $LATEST_TAG"

# URLs for the manifests
K8S_MANIFEST_URL="https://raw.githubusercontent.com/open-telemetry/opentelemetry-collector-releases/main/distributions/otelcol-k8s/manifest.yaml"
CONTRIB_MANIFEST_URL="https://raw.githubusercontent.com/open-telemetry/opentelemetry-collector-releases/main/distributions/otelcol-contrib/manifest.yaml"

# Download manifests
echo "Downloading manifests..."
curl -sSL "$K8S_MANIFEST_URL" -o k8s_manifest.yaml
curl -sSL "$CONTRIB_MANIFEST_URL" -o contrib_manifest.yaml

# 1. Update builder-config.yaml
echo "Updating builder-config.yaml..."
# Start with k8s manifest and apply our customizations
yq eval -i '
  .dist.name = "suse-ai-opentelemetry-collector" |
  .dist.description = "Minimal OTel Collector distribution for monitoring SUSE AI" |
  .dist.output_path = "./suse-ai-opentelemetry-collector" |
  del(.dist.module) |
  del(.dist.version) |
  del(.dist.build_tags)
' k8s_manifest.yaml

# Extract elasticsearchreceiver from contrib
ES_RECEIVER=$(yq eval '.receivers[] | select(.gomod == "*elasticsearchreceiver*")' contrib_manifest.yaml)
if [ -z "$ES_RECEIVER" ]; then
  echo "Error: Could not find elasticsearchreceiver in contrib manifest"
  exit 1
fi

# Add the receiver to the manifest
yq eval -i ".receivers += $(echo "$ES_RECEIVER" | yq eval -o=json -)" k8s_manifest.yaml

# Add the topology exporter (local module)
yq eval -i '.exporters += {"gomod": "github.com/suse/suse-ai-opentelemetry-collector/topologyexporter v0.0.0", "path": "./topologyexporter"}' k8s_manifest.yaml

# Replace the current builder-config.yaml
mv k8s_manifest.yaml builder-config.yaml
rm contrib_manifest.yaml

# 2. Update Containerfile
echo "Updating Containerfile..."
sed -i "s|builder@v[0-9.]*|builder@$LATEST_TAG|g" Containerfile

# 3. Regenerate code
echo "Installing builder..."
go install "go.opentelemetry.io/collector/cmd/builder@$LATEST_TAG"

echo "Running builder (skipping compilation)..."
$(go env GOPATH)/bin/builder --config builder-config.yaml --skip-compilation

# Clean up any leftover binary just in case
rm -f ./suse-ai-opentelemetry-collector/suse-ai-opentelemetry-collector

echo "Update process completed successfully."
