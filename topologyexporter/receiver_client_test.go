package topologyexporter

import (
	"encoding/json"
	"io"
	"net/http"
	"net/http/httptest"
	"testing"
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

	client := newReceiverClient(server.URL, "test-api-key", Instance{Type: "suse-ai", URL: "local"}, http.DefaultClient)

	components := []Component{{
		ExternalID: "suse-ai:product:inference-engine:ollama",
		Type:       Type{Name: "inference-engine"},
		Data: ComponentData{
			Name:        "ollama",
			Layer:       "Services",
			Domain:      "SUSE AI",
			Labels:      []string{"suse.ai.component.type:inference-engine"},
			Identifiers: []string{"suse-ai:product:inference-engine:ollama"},
		},
	}}

	relations := []Relation{{
		ExternalID: "suse-ai:product:ui:open-webui --> suse-ai:product:inference-engine:ollama",
		SourceID:   "suse-ai:product:ui:open-webui",
		TargetID:   "suse-ai:product:inference-engine:ollama",
		Type:       Type{Name: "uses"},
	}}

	err := client.send(components, relations)
	if err != nil {
		t.Fatalf("unexpected error: %v", err)
	}

	if receivedAPIKey != "test-api-key" {
		t.Errorf("expected api_key=test-api-key, got %s", receivedAPIKey)
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

func TestReceiverClientHandlesServerError(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.WriteHeader(http.StatusInternalServerError)
	}))
	defer server.Close()

	client := newReceiverClient(server.URL, "test-key", Instance{Type: "suse-ai", URL: "local"}, http.DefaultClient)
	err := client.send([]Component{}, []Relation{})
	if err == nil {
		t.Error("expected error for 500 response")
	}
}
