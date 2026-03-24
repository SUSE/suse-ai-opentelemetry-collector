package topologyexporter

import (
	"fmt"
	"strings"
	"sync"

	"go.opentelemetry.io/collector/pdata/ptrace"
)

var (
	applicationLayerTypes = map[string]bool{"application": true, "ui": true, "agent": true}
	modelLayerTypes       = map[string]bool{"llm-model": true}
	vectorDBSystems       = map[string]bool{"milvus": true, "qdrant": true}
	searchEngineSystems   = map[string]bool{"opensearch": true, "elasticsearch": true}
)

type topologyAccumulator struct {
	mu         sync.Mutex
	components map[string]Component
	relations  map[string]Relation
	namespace  string
}

func newTopologyAccumulator(namespace string) *topologyAccumulator {
	return &topologyAccumulator{
		components: make(map[string]Component),
		relations:  make(map[string]Relation),
		namespace:  namespace,
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
	externalID := fmt.Sprintf("suse-ai:product:%s:%s", componentType, name)

	if _, exists := a.components[externalID]; !exists {
		labels := []string{
			fmt.Sprintf("suse.ai.component.type:%s", componentType),
		}
		if a.namespace != "" {
			labels = append(labels, fmt.Sprintf("k8s.namespace.name:%s", a.namespace))
		}

		a.components[externalID] = Component{
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

	return externalID
}

func (a *topologyAccumulator) ensureRelation(sourceID, targetID, relationType string) {
	key := fmt.Sprintf("%s --> %s", sourceID, targetID)

	if _, exists := a.relations[key]; !exists {
		a.relations[key] = Relation{
			ExternalID: key,
			SourceID:   sourceID,
			TargetID:   targetID,
			Type:       Type{Name: relationType},
			Data:       make(map[string]interface{}),
		}
	}
}

func (a *topologyAccumulator) snapshot() ([]Component, []Relation) {
	a.mu.Lock()
	defer a.mu.Unlock()

	components := make([]Component, 0, len(a.components))
	for _, c := range a.components {
		components = append(components, c)
	}

	relations := make([]Relation, 0, len(a.relations))
	for _, r := range a.relations {
		relations = append(relations, r)
	}

	a.components = make(map[string]Component)
	a.relations = make(map[string]Relation)

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
