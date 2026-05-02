FROM dp.apps.rancher.io/containers/go:1.25.5 AS build-stage

WORKDIR /build

COPY ./builder-config.yaml builder-config.yaml
COPY ./topologyexporter ./topologyexporter

RUN --mount=type=cache,target=/root/.cache/go-build \
    GO111MODULE=on go install go.opentelemetry.io/collector/cmd/builder@v0.151.0

RUN --mount=type=cache,target=/root/.cache/go-build \
    $(go env GOPATH)/bin/builder --config builder-config.yaml

FROM dp.apps.rancher.io/containers/bci-micro:15.7

ARG USER_UID=10001
USER ${USER_UID}

COPY ./collector-config.yaml /otelcol/collector-config.yaml

COPY --from=build-stage /var/lib/ca-certificates/ca-bundle.pem /etc/ssl/certs/ca-certificates.crt

COPY --chmod=755 --from=build-stage /build/suse-ai-opentelemetry-collector/suse-ai-opentelemetry-collector /otelcol/otelcol-custom

ENTRYPOINT ["/otelcol/otelcol-custom"]
CMD ["--config", "/otelcol/collector-config.yaml"]

EXPOSE 4317 4318 12001
