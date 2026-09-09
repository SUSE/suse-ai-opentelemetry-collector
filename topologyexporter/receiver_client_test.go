package topologyexporter

import (
	"context"
	"encoding/json"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"net/url"
	"strings"
	"testing"
	"time"
)

func TestReceiverClientSendsCorrectPayload(t *testing.T) {
	var receivedPayload Payload
	var receivedAPIKey string

	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		receivedAPIKey = r.URL.Query().Get("api_key")
		body, _ := io.ReadAll(r.Body)
		json.Unmarshal(body, &receivedPayload)
		w.WriteHeader(http.StatusOK)
	}))
	defer server.Close()

	const apiKey = "test&api=key +/?"
	client := newReceiverClient(server.URL, apiKey, Instance{Type: "suse-ai", URL: "local"}, http.DefaultClient)

	components := []Component{{
		ExternalID: "urn:suse-ai:product:inference-engine:ollama",
		Type:       Type{Name: "inference-engine"},
		Data: ComponentData{
			Name:        "ollama",
			Layer:       "Services",
			Domain:      "SUSE AI",
			Labels:      []string{"suse.ai.component.type:inference-engine"},
			Identifiers: []string{"urn:suse-ai:product:inference-engine:ollama"},
		},
	}}

	relations := []Relation{{
		ExternalID: "urn:suse-ai:product:ui:open-webui --> urn:suse-ai:product:inference-engine:ollama",
		SourceID:   "urn:suse-ai:product:ui:open-webui",
		TargetID:   "urn:suse-ai:product:inference-engine:ollama",
		Type:       Type{Name: "uses"},
	}}

	err := client.send(context.Background(), components, relations)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if receivedAPIKey != apiKey {
		t.Errorf("expected api_key=%q, got %q", apiKey, receivedAPIKey)
	}
	if len(receivedPayload.Topologies) != 1 {
		t.Fatalf("expected 1 topology, got %d", len(receivedPayload.Topologies))
	}
	topo := receivedPayload.Topologies[0]
	if !topo.StartSnapshot || !topo.StopSnapshot {
		t.Error("expected start_snapshot and stop_snapshot to be true")
	}
	if topo.Instance.Type != "suse-ai" {
		t.Errorf("unexpected instance type: %s", topo.Instance.Type)
	}
	if len(topo.Components) != 1 {
		t.Errorf("expected 1 component, got %d", len(topo.Components))
	}
	if len(topo.Relations) != 1 {
		t.Errorf("expected 1 relation, got %d", len(topo.Relations))
	}
}

func TestReceiverClientRedactsTransportErrors(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(http.ResponseWriter, *http.Request) {}))
	server.Close()
	const key = "secret&key=with spaces"
	client := newReceiverClient(server.URL, key, Instance{}, http.DefaultClient)
	err := client.send(context.Background(), nil, nil)
	if err == nil {
		t.Fatal("expected connection failure")
	}
	for _, secret := range []string{key, url.QueryEscape(key), "api_key="} {
		if strings.Contains(err.Error(), secret) {
			t.Fatalf("transport error contains credentials: %v", err)
		}
	}
}

func TestReceiverClientHonorsDeadline(t *testing.T) {
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
	client := newReceiverClient(server.URL, "test-key", Instance{}, http.DefaultClient)
	ctx, cancel := context.WithTimeout(context.Background(), 50*time.Millisecond)
	defer cancel()
	err := client.send(ctx, nil, nil)
	if !errors.Is(err, context.DeadlineExceeded) {
		t.Fatalf("expected deadline exceeded, got %v", err)
	}
}

func TestReceiverClientRejectsRedirect(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Location", "/elsewhere")
		w.WriteHeader(http.StatusTemporaryRedirect)
	}))
	defer server.Close()
	client := newReceiverClient(server.URL, "test-key", Instance{}, &http.Client{
		CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
	})
	if err := client.send(context.Background(), nil, nil); err == nil {
		t.Fatal("redirect must not be reported as successful delivery")
	}
}

func TestReceiverClientHandlesServerError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer server.Close()

	client := newReceiverClient(server.URL, "test-key", Instance{Type: "suse-ai", URL: "local"}, http.DefaultClient)
	err := client.send(context.Background(), []Component{}, []Relation{})
	if err == nil {
		t.Error("expected error for 500 response")
	}
}
