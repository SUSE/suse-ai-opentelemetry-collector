package topologyexporter

import (
	"context"
	"log/slog"
	"net/http"
	"time"

	"go.opentelemetry.io/collector/component"
	"go.opentelemetry.io/collector/pdata/ptrace"
)

// topologyInstanceType and topologyStreamID form the SUSE Observability receiver
// stream (sts_topo_<type>_<id>). They are a fixed contract with the stackpack's
// "SUSE AI Topology" DataSource (integrationType + topic) in
// suse-ai-observability-extension synchronization.sty, so they are constants, not
// config: any other value routes topology to a topic the sync never reads.
const (
	topologyInstanceType = "suse-ai"
	topologyStreamID     = "collector"
)

type topologyExporter struct {
	cfg         *Config
	accumulator *topologyAccumulator
	client      *receiverClient
	done        chan struct{}
}

func newTopologyExporter(cfg *Config) *topologyExporter {
	return &topologyExporter{
		cfg:         cfg,
		accumulator: newTopologyAccumulator(cfg.Namespace, cfg.ClusterName),
		done:        make(chan struct{}),
	}
}

func (e *topologyExporter) start(ctx context.Context, host component.Host) error {
	tlsConfig, err := e.cfg.TLS.LoadTLSConfig(ctx)
	if err != nil {
		return err
	}

	transport := &http.Transport{}
	if tlsConfig != nil {
		transport.TLSClientConfig = tlsConfig
	}
	httpClient := &http.Client{Transport: transport}

	instance := Instance{
		Type: topologyInstanceType,
		URL:  topologyStreamID,
	}
	e.client = newReceiverClient(e.cfg.Endpoint, e.cfg.APIKey, instance, httpClient)

	go e.flushLoop()

	slog.Info("topology exporter started",
		"endpoint", e.cfg.Endpoint,
		"flush_interval", e.cfg.FlushInterval,
	)
	return nil
}

func (e *topologyExporter) flushLoop() {
	ticker := time.NewTicker(e.cfg.FlushInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			e.flush()
		case <-e.done:
			return
		}
	}
}

func (e *topologyExporter) flush() {
	components, relations := e.accumulator.snapshot()
	if err := e.client.send(components, relations); err != nil {
		slog.Warn("failed to flush topology", "error", err)
	}
}

func (e *topologyExporter) pushTraces(ctx context.Context, td ptrace.Traces) error {
	e.accumulator.processTraces(td)
	return nil
}

func (e *topologyExporter) shutdown(ctx context.Context) error {
	close(e.done)
	e.flush()
	return nil
}
