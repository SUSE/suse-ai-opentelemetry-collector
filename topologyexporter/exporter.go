package topologyexporter

import (
	"context"
	"errors"
	"log/slog"
	"net/http"
	"sync"
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
	cfg          *Config
	accumulator  *topologyAccumulator
	client       *receiverClient
	done         chan struct{}
	cancel       context.CancelFunc
	shutdownOnce sync.Once
	shutdownErr  error
}

func newTopologyExporter(cfg *Config) *topologyExporter {
	return &topologyExporter{
		cfg:         cfg,
		accumulator: newTopologyAccumulator(cfg.Namespace, cfg.ClusterName, cfg.Retention),
		done:        make(chan struct{}),
	}
}

func (e *topologyExporter) start(ctx context.Context, host component.Host) error {
	tlsConfig, err := e.cfg.TLS.LoadTLSConfig(ctx)
	if err != nil {
		return err
	}

	transport := http.DefaultTransport.(*http.Transport).Clone()
	if tlsConfig != nil {
		transport.TLSClientConfig = tlsConfig
	}
	httpClient := &http.Client{
		Transport: transport,
		Timeout:   e.cfg.Timeout,
		CheckRedirect: func(*http.Request, []*http.Request) error {
			return http.ErrUseLastResponse
		},
	}

	instance := Instance{
		Type: topologyInstanceType,
		URL:  topologyStreamID,
	}
	e.client = newReceiverClient(e.cfg.Endpoint, string(e.cfg.APIKey), instance, httpClient)

	loopCtx, cancel := context.WithCancel(context.Background())
	e.cancel = cancel
	go e.flushLoop(loopCtx)

	slog.Info("topology exporter started",
		"endpoint", e.cfg.Endpoint,
		"flush_interval", e.cfg.FlushInterval,
	)
	return nil
}

func (e *topologyExporter) flushLoop(ctx context.Context) {
	defer close(e.done)
	ticker := time.NewTicker(e.cfg.FlushInterval)
	defer ticker.Stop()

	for {
		select {
		case <-ticker.C:
			if err := e.flush(ctx); err != nil && !errors.Is(err, context.Canceled) {
				slog.Warn("failed to flush topology", "error", err)
			}
		case <-ctx.Done():
			return
		}
	}
}

func (e *topologyExporter) flush(ctx context.Context) error {
	components, relations := e.accumulator.snapshot()
	return e.client.send(ctx, components, relations)
}

func (e *topologyExporter) pushTraces(ctx context.Context, td ptrace.Traces) error {
	e.accumulator.processTraces(td)
	return nil
}

func (e *topologyExporter) shutdown(ctx context.Context) error {
	e.shutdownOnce.Do(func() {
		if e.cancel == nil {
			return
		}
		e.cancel()
		defer e.client.httpClient.CloseIdleConnections()
		select {
		case <-e.done:
			// Wait for the periodic request to finish before the final snapshot.
			e.shutdownErr = e.flush(ctx)
		case <-ctx.Done():
			e.shutdownErr = ctx.Err()
		}
	})
	return e.shutdownErr
}
