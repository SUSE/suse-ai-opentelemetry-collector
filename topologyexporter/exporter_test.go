package topologyexporter

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"net/http/httptest"
	"sync"
	"sync/atomic"
	"testing"
	"time"

	"go.opentelemetry.io/collector/component/componenttest"
)

func TestExporterFullPipeline(t *testing.T) {
	var mu sync.Mutex
	var receivedPayloads []Payload

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		body, _ := io.ReadAll(r.Body)
		var p Payload
		json.Unmarshal(body, &p)
		mu.Lock()
		receivedPayloads = append(receivedPayloads, p)
		mu.Unlock()
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	cfg := createDefaultConfig()
	cfg.Endpoint = server.URL
	cfg.APIKey = "test-key"
	cfg.FlushInterval = 100 * time.Millisecond
	cfg.Namespace = "suse-ai"

	exp := newTopologyExporter(cfg)

	err := exp.start(context.Background(), componenttest.NewNopHost())
	if err != nil {
		t.Fatalf("start failed: %v", err)
	}

	td := makeTraces(
		map[string]string{"suse.ai.component.name": "open-webui", "suse.ai.component.type": "ui"},
		map[string]string{"gen_ai.provider.name": "ollama", "gen_ai.request.model": "llama3.2"},
	)
	err = exp.pushTraces(context.Background(), td)
	if err != nil {
		t.Fatalf("pushTraces failed: %v", err)
	}

	time.Sleep(300 * time.Millisecond)

	err = exp.shutdown(context.Background())
	if err != nil {
		t.Fatalf("shutdown failed: %v", err)
	}

	mu.Lock()
	defer mu.Unlock()

	if len(receivedPayloads) == 0 {
		t.Fatal("expected at least 1 payload")
	}

	var found bool
	for _, p := range receivedPayloads {
		topo := p.Topologies[0]
		if len(topo.Components) == 3 && len(topo.Relations) == 2 {
			found = true
			break
		}
	}
	if !found {
		t.Error("expected a payload with 3 components and 2 relations")
	}
}

func TestExporterShutdownCancelsInFlightFlush(t *testing.T) {
	started := make(chan struct{})
	release := make(chan struct{})
	var requests atomic.Int32
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		if requests.Add(1) == 1 {
			close(started)
			select {
			case <-r.Context().Done():
			case <-release:
			}
		}
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()
	defer close(release)
	cfg := createDefaultConfig()
	cfg.Endpoint, cfg.APIKey = server.URL, "test-key"
	cfg.FlushInterval = 10 * time.Millisecond
	exp := newTopologyExporter(cfg)
	if err := exp.start(context.Background(), componenttest.NewNopHost()); err != nil {
		t.Fatal(err)
	}
	defer exp.shutdown(context.Background())
	select {
	case <-started:
	case <-time.After(2 * time.Second):
		t.Fatal("periodic flush did not start")
	}
	ctx, cancel := context.WithTimeout(context.Background(), time.Second)
	defer cancel()
	if err := exp.shutdown(ctx); err != nil {
		t.Fatalf("shutdown must cancel the periodic request and send a final snapshot: %v", err)
	}
	if got := requests.Load(); got != 2 {
		t.Fatalf("expected one periodic request and one final snapshot, got %d", got)
	}
	if err := exp.shutdown(ctx); err != nil {
		t.Fatalf("repeated shutdown failed: %v", err)
	}
	if requests.Load() != 2 {
		t.Fatal("repeated shutdown sent an extra snapshot")
	}
}

func TestExporterShutdownHonorsDeadline(t *testing.T) {
	release := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		select {
		case <-r.Context().Done():
		case <-release:
		}
	}))
	defer server.Close()
	defer close(release)
	cfg := createDefaultConfig()
	cfg.Endpoint, cfg.APIKey = server.URL, "test-key"
	exp := newTopologyExporter(cfg)
	if err := exp.start(context.Background(), componenttest.NewNopHost()); err != nil {
		t.Fatal(err)
	}
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	if err := exp.shutdown(ctx); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("shutdown must preserve the deadline error, got %v", err)
	}
}

func TestExporterRequestTimeout(t *testing.T) {
	release := make(chan struct{})
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		_, _ = io.Copy(io.Discard, r.Body)
		select {
		case <-r.Context().Done():
		case <-release:
		}
	}))
	defer server.Close()
	defer close(release)
	cfg := createDefaultConfig()
	cfg.Endpoint, cfg.APIKey = server.URL, "test-key"
	cfg.Timeout = 50 * time.Millisecond
	exp := newTopologyExporter(cfg)
	if err := exp.start(context.Background(), componenttest.NewNopHost()); err != nil {
		t.Fatal(err)
	}
	if err := exp.shutdown(context.Background()); !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("request timeout must bound a shutdown without a context deadline, got %v", err)
	}
}

func TestConfigValidationAndSecretMasking(t *testing.T) {
	cfg := createDefaultConfig()
	cfg.Endpoint, cfg.APIKey = "https://observability.example/base", "test-secret"
	if err := cfg.Validate(); err != nil {
		t.Fatal(err)
	}
	if got := fmt.Sprint(cfg.APIKey); got == "test-secret" {
		t.Fatal("API key must be masked when formatted")
	}
	for _, endpoint := range []string{"relative/path", "ftp://example.com", "https://user:secret@example.com", "https://example.com?api_key=secret", "https://example.com#fragment"} {
		cfg.Endpoint = endpoint
		if err := cfg.Validate(); err == nil {
			t.Errorf("expected invalid endpoint %q to be rejected", endpoint)
		}
	}
	cfg.Endpoint = "https://observability.example"
	cfg.Timeout = 0
	if err := cfg.Validate(); err == nil {
		t.Fatal("unbounded timeout must be rejected")
	}
}
