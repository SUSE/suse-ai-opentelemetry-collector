FROM --platform=$BUILDPLATFORM dp.apps.rancher.io/containers/go:1.26.10 AS build-stage

WORKDIR /build

COPY ./builder-config.yaml builder-config.yaml
COPY ./topologyexporter ./topologyexporter

RUN --mount=type=cache,target=/root/.cache/go-build \
    GO111MODULE=on go install go.opentelemetry.io/collector/cmd/builder@v0.164.0

ARG TARGETOS
ARG TARGETARCH
RUN --mount=type=cache,target=/root/.cache/go-build \
    GOOS=${TARGETOS} GOARCH=${TARGETARCH} \
    "$(go env GOPATH)/bin/builder" --config builder-config.yaml

FROM dp.apps.rancher.io/containers/bci-micro:15.7

ARG USER_UID=10001
USER ${USER_UID}

COPY ./collector-config.yaml /otelcol/collector-config.yaml
COPY ./litellm-receiver.yaml /otelcol/litellm-receiver.yaml
COPY ./examples/ollama-runtime.yaml /otelcol/ollama-runtime.yaml
COPY ./examples/workload-probes.yaml /otelcol/workload-probes.yaml

COPY --from=build-stage /var/lib/ca-certificates/ca-bundle.pem /etc/ssl/certs/ca-certificates.crt

COPY --chmod=755 --from=build-stage /build/suse-ai-opentelemetry-collector/suse-ai-opentelemetry-collector /otelcol/otelcol-custom

# Validation placeholders apply only during the build, not at runtime.
ARG API_KEY=validation
ARG ELASTICSEARCH_PASSWORD=validation
ARG K8S_CLUSTER_NAME=validation
RUN ["/otelcol/otelcol-custom", "validate", "--config=/otelcol/collector-config.yaml", "--config=/otelcol/litellm-receiver.yaml"]
RUN ["/otelcol/otelcol-custom", "validate", "--config=/otelcol/collector-config.yaml", "--config=/otelcol/ollama-runtime.yaml"]
RUN ["/otelcol/otelcol-custom", "validate", "--config=/otelcol/collector-config.yaml", "--config=/otelcol/workload-probes.yaml"]
RUN ["/otelcol/otelcol-custom", "validate", "--config=/otelcol/collector-config.yaml", "--config=/otelcol/litellm-receiver.yaml", "--config=/otelcol/ollama-runtime.yaml", "--config=/otelcol/workload-probes.yaml"]

ENTRYPOINT ["/otelcol/otelcol-custom"]
CMD ["--config", "/otelcol/collector-config.yaml"]

EXPOSE 4317 4318 13133 14250 14268
