package topologyexporter

import (
	"fmt"
	"strings"
	"sync"
	"time"

	"go.opentelemetry.io/collector/pdata/ptrace"
)

var (
	applicationLayerTypes = map[string]bool{"application": true, "ui": true, "agent": true}
	modelLayerTypes       = map[string]bool{"llm-model": true}
	vectorDBSystems       = map[string]bool{"milvus": true, "qdrant": true}
	searchEngineSystems   = map[string]bool{"opensearch": true, "elasticsearch": true}
)

type componentEntry struct {
	component Component
	lastSeen  time.Time
}

type relationEntry struct {
	relation Relation
	lastSeen time.Time
}

type topologyAccumulator struct {
	mu          sync.Mutex
	components  map[string]componentEntry
	relations   map[string]relationEntry
	namespace   string
	clusterName string
	retention   time.Duration
	now         func() time.Time
}

func newTopologyAccumulator(namespace, clusterName string, retention time.Duration) *topologyAccumulator {
	return &topologyAccumulator{
		components:  make(map[string]componentEntry),
		relations:   make(map[string]relationEntry),
		namespace:   namespace,
		clusterName: clusterName,
		retention:   retention,
		now:         time.Now,
	}
}

func (a *topologyAccumulator) processTraces(td ptrace.Traces) {
	a.mu.Lock()
	defer a.mu.Unlock()

	for i := 0; i < td.ResourceSpans().Len(); i++ {
		rs := td.ResourceSpans().At(i)
		resource := rs.Resource()

		// Resolve component name: prefer suse.ai.component.name, fallback to service.name
		var appName string
		if cn, ok := resource.Attributes().Get("suse.ai.component.name"); ok {
			appName = cn.Str()
		} else if sn, ok := resource.Attributes().Get("service.name"); ok {
			appName = sn.Str()
		} else {
			continue
		}

		componentType := "application"
		if ct, ok := resource.Attributes().Get("suse.ai.component.type"); ok {
			componentType = ct.Str()
		}

		appID := a.ensureComponent(appName, componentType)

		for j := 0; j < rs.ScopeSpans().Len(); j++ {
			ss := rs.ScopeSpans().At(j)
			for k := 0; k < ss.Spans().Len(); k++ {
				span := ss.Spans().At(k)
				a.processSpan(appID, span)
			}
		}
	}
}

func (a *topologyAccumulator) processSpan(appID string, span ptrace.Span) {
	attrs := span.Attributes()

	if provider, ok := attrs.Get("gen_ai.provider.name"); ok {
		providerName := provider.Str()
		providerID := a.ensureComponent(providerName, "inference-engine")
		a.ensureRelation(appID, providerID, "uses")

		if model, ok := attrs.Get("gen_ai.request.model"); ok {
			modelName := model.Str()
			modelID := a.ensureComponent(modelName, "llm-model")
			a.ensureRelation(providerID, modelID, "runs")
		}
	}

	if dbSystem, ok := attrs.Get("db.system"); ok {
		systemName := strings.ToLower(dbSystem.Str())

		if vectorDBSystems[systemName] {
			dbID := a.ensureComponent(systemName, "vectordb")
			a.ensureRelation(appID, dbID, "uses")
		} else if searchEngineSystems[systemName] {
			dbID := a.ensureComponent(systemName, "search-engine")
			a.ensureRelation(appID, dbID, "uses")
		}
	}
}

func (a *topologyAccumulator) ensureComponent(name, componentType string) string {
	externalID := fmt.Sprintf("urn:suse-ai:product:%s:%s", componentType, name)

	entry, exists := a.components[externalID]
	if !exists {
		labels := []string{
			fmt.Sprintf("suse.ai.component.type:%s", componentType),
		}
		if a.namespace != "" {
			labels = append(labels, fmt.Sprintf("k8s.namespace.name:%s", a.namespace))
		}
		// Cluster is metadata only — the externalID stays cluster-agnostic so the
		// same product aggregates across clusters.
		if a.clusterName != "" {
			labels = append(labels, fmt.Sprintf("k8s.cluster.name:%s", a.clusterName))
		}

		entry.component = Component{
			ExternalID: externalID,
			Type:       Type{Name: componentType},
			Data: ComponentData{
				Name:             name,
				Layer:            layerFor(componentType),
				Domain:           "SUSE AI",
				Labels:           labels,
				Identifiers:      []string{externalID},
				CustomProperties: make(map[string]interface{}),
			},
			SourceProperties: make(map[string]interface{}),
		}
	}

	entry.lastSeen = a.now()
	a.components[externalID] = entry

	return externalID
}

func (a *topologyAccumulator) ensureRelation(sourceID, targetID, relationType string) {
	key := fmt.Sprintf("%s --> %s", sourceID, targetID)

	entry, exists := a.relations[key]
	if !exists {
		entry.relation = Relation{
			ExternalID: key,
			SourceID:   sourceID,
			TargetID:   targetID,
			Type:       Type{Name: relationType},
			Data:       make(map[string]interface{}),
		}
	}

	entry.lastSeen = a.now()
	a.relations[key] = entry
}

// snapshot evicts any component or relation not seen within the retention
// window, then returns everything that remains. Entries persist across
// snapshots so the topology is not forgotten between sparse traces.
func (a *topologyAccumulator) snapshot() ([]Component, []Relation) {
	a.mu.Lock()
	defer a.mu.Unlock()

	cutoff := a.now().Add(-a.retention)

	components := make([]Component, 0, len(a.components))
	for id, c := range a.components {
		if c.lastSeen.Before(cutoff) {
			delete(a.components, id)
			continue
		}
		components = append(components, c.component)
	}

	relations := make([]Relation, 0, len(a.relations))
	for key, r := range a.relations {
		if r.lastSeen.Before(cutoff) {
			delete(a.relations, key)
			continue
		}
		relations = append(relations, r.relation)
	}

	return components, relations
}

func layerFor(componentType string) string {
	if applicationLayerTypes[componentType] {
		return "Applications"
	}
	if modelLayerTypes[componentType] {
		return "Models"
	}
	return "Services"
}
