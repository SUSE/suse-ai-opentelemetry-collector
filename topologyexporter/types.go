package topologyexporter

import (
	"time"
)

// Receiver API DTOs for SUSE Observability /receiver/stsAgent/intake

type Type struct {
	Name string `json:"name"`
}

type ComponentData struct {
	Name             string                 `json:"name"`
	Layer            string                 `json:"layer"`
	Domain           string                 `json:"domain"`
	Environment      string                 `json:"environment"`
	Labels           []string               `json:"labels"`
	Identifiers      []string               `json:"identifiers"`
	CustomProperties map[string]interface{} `json:"custom_properties"`
}

type Component struct {
	ExternalID       string                 `json:"externalId"`
	Type             Type                   `json:"type"`
	Data             ComponentData          `json:"data"`
	SourceProperties map[string]interface{} `json:"sourceProperties"`
}

type Relation struct {
	ExternalID string                 `json:"externalId"`
	SourceID   string                 `json:"sourceId"`
	TargetID   string                 `json:"targetId"`
	Type       Type                   `json:"type"`
	Data       map[string]interface{} `json:"data"`
}

type Instance struct {
	Type string `json:"type"`
	URL  string `json:"url"`
}

type Topology struct {
	StartSnapshot bool        `json:"start_snapshot"`
	StopSnapshot  bool        `json:"stop_snapshot"`
	Instance      Instance    `json:"instance"`
	Components    []Component `json:"components"`
	Relations     []Relation  `json:"relations"`
	DeleteIDs     []string    `json:"delete_ids"`
}

type Payload struct {
	CollectionTimestamp int64            `json:"collection_timestamp"`
	InternalHostname    string           `json:"internalHostname"`
	Topologies          []Topology       `json:"topologies"`
	Events              map[string][]any `json:"events"`
	Metrics             []any            `json:"metrics"`
	ServiceChecks       []any            `json:"service_checks"`
	Health              []any            `json:"health"`
}

func NewPayload(instance Instance, components []Component, relations []Relation) *Payload {
	return &Payload{
		CollectionTimestamp: time.Now().Unix(),
		InternalHostname:    "otelcol-suse-ai",
		Topologies: []Topology{{
			StartSnapshot: true,
			StopSnapshot:  true,
			Instance:      instance,
			Components:    components,
			Relations:     relations,
			DeleteIDs:     []string{},
		}},
		Events:        make(map[string][]any),
		Metrics:       []any{},
		ServiceChecks: []any{},
		Health:        []any{},
	}
}
