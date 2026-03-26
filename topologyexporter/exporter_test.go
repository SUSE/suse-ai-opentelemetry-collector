package topologyexporter

import (
	"context"
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"sync"
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
