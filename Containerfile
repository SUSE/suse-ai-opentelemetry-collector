FROM --platform=$BUILDPLATFORM dp.apps.rancher.io/containers/go:1.26.10 AS build-stage

WORKDIR /build

COPY ./builder-config.yaml builder-config.yaml
COPY ./topologyexporter ./topologyexporter

RUN --mount=type=cache,target=/root/.cache/go-build \
    GO111MODULE=on go install go.opentelemetry.io/collector/cmd/builder@v0.164.0

# Keep reviewed dependency fixes from go.mod/go.sum when generating the distribution.
COPY ./suse-ai-opentelemetry-collector/go.mod ./suse-ai-opentelemetry-collector/go.sum ./suse-ai-opentelemetry-collector/

ARG TARGETOS
ARG TARGETARCH
RUN --mount=type=cache,target=/root/.cache/go-build \
    GOOS=${TARGETOS} GOARCH=${TARGETARCH} GOFLAGS=-mod=readonly \
    "$(go env GOPATH)/bin/builder" --config builder-config.yaml --skip-get-modules

FROM dp.apps.rancher.io/containers/bci-micro:15.7

ARG USER_UID=10001
USER ${USER_UID}

COPY ./collector-config.yaml /otelcol/collector-config.yaml
COPY ./litellm-receiver.yaml /otelcol/litellm-receiver.yaml
COPY ./litellm-receiver-no-auth.yaml /otelcol/litellm-receiver-no-auth.yaml
COPY ./milvus.yaml /otelcol/milvus.yaml
COPY ./qdrant.yaml /otelcol/qdrant.yaml
COPY ./opensearch.yaml /otelcol/opensearch.yaml
COPY ./examples/ollama-runtime.yaml /otelcol/ollama-runtime.yaml
COPY ./examples/workload-probes.yaml /otelcol/workload-probes.yaml

COPY --from=build-stage /var/lib/ca-certificates/ca-bundle.pem /etc/ssl/certs/ca-certificates.crt

COPY --chmod=755 --from=build-stage /build/suse-ai-opentelemetry-collector/suse-ai-opentelemetry-collector /otelcol/otelcol-custom

# Validation placeholders apply only during the build, not at runtime.
ARG API_KEY=validation
ARG ELASTICSEARCH_PASSWORD=validation
ARG K8S_CLUSTER_NAME=validation
RUN --mount=type=bind,source=tests/fixtures/litellm-metrics-key,target=/etc/litellm-metrics/key \
    ["/otelcol/otelcol-custom", "validate", "--config=/otelcol/collector-config.yaml", "--config=/otelcol/litellm-receiver.yaml"]
RUN ["/otelcol/otelcol-custom", "validate", "--config=/otelcol/collector-config.yaml", "--config=/otelcol/litellm-receiver-no-auth.yaml"]
RUN ["/otelcol/otelcol-custom", "validate", "--config=/otelcol/collector-config.yaml", "--config=/otelcol/ollama-runtime.yaml"]
RUN ["/otelcol/otelcol-custom", "validate", "--config=/otelcol/collector-config.yaml", "--config=/otelcol/workload-probes.yaml"]
RUN ["/otelcol/otelcol-custom", "validate", "--config=/otelcol/collector-config.yaml", "--config=/otelcol/milvus.yaml"]
RUN ["/otelcol/otelcol-custom", "validate", "--config=/otelcol/collector-config.yaml", "--config=/otelcol/qdrant.yaml"]
RUN ["/otelcol/otelcol-custom", "validate", "--config=/otelcol/collector-config.yaml", "--config=/otelcol/opensearch.yaml"]
RUN --mount=type=bind,source=tests/fixtures/litellm-metrics-key,target=/etc/litellm-metrics/key \
    ["/otelcol/otelcol-custom", "validate", "--config=/otelcol/collector-config.yaml", "--config=/otelcol/litellm-receiver.yaml", "--config=/otelcol/ollama-runtime.yaml", "--config=/otelcol/workload-probes.yaml", "--config=/otelcol/milvus.yaml", "--config=/otelcol/qdrant.yaml", "--config=/otelcol/opensearch.yaml"]

ENTRYPOINT ["/otelcol/otelcol-custom"]
CMD ["--config", "/otelcol/collector-config.yaml"]

EXPOSE 4317 4318 13133 14250 14268
