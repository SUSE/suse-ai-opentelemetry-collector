package topologyexporter

import (
	"sync"
	"testing"

	"go.opentelemetry.io/collector/pdata/ptrace"
)

func makeTraces(resourceAttrs map[string]string, spanAttrs map[string]string) ptrace.Traces {
	td := ptrace.NewTraces()
	rs := td.ResourceSpans().AppendEmpty()
	for k, v := range resourceAttrs {
		rs.Resource().Attributes().PutStr(k, v)
	}
	ss := rs.ScopeSpans().AppendEmpty()
	span := ss.Spans().AppendEmpty()
	span.SetName("test-span")
	for k, v := range spanAttrs {
		span.Attributes().PutStr(k, v)
	}
	return td
}

func TestSkipSpanWithoutComponentName(t *testing.T) {
	acc := newTopologyAccumulator("test-ns")
	td := makeTraces(map[string]string{}, map[string]string{"gen_ai.provider.name": "ollama"})
	acc.processTraces(td)
	components, relations := acc.snapshot()
	if len(components) != 0 {
		t.Errorf("expected 0 components, got %d", len(components))
	}
	if len(relations) != 0 {
		t.Errorf("expected 0 relations, got %d", len(relations))
	}
}

func TestDiscoverAppComponent(t *testing.T) {
	acc := newTopologyAccumulator("test-ns")
	td := makeTraces(
		map[string]string{"suse.ai.component.name": "my-app", "suse.ai.component.type": "ui"},
		map[string]string{},
	)
	acc.processTraces(td)
	components, _ := acc.snapshot()
	if len(components) != 1 {
		t.Fatalf("expected 1 component, got %d", len(components))
	}
	c := components[0]
	if c.ExternalID != "suse-ai:product:ui:my-app" {
		t.Errorf("unexpected externalId: %s", c.ExternalID)
	}
	if c.Type.Name != "ui" {
		t.Errorf("unexpected type: %s", c.Type.Name)
	}
	if c.Data.Layer != "Applications" {
		t.Errorf("unexpected layer: %s", c.Data.Layer)
	}
}

func TestDefaultComponentType(t *testing.T) {
	acc := newTopologyAccumulator("test-ns")
	td := makeTraces(
		map[string]string{"suse.ai.component.name": "my-app"},
		map[string]string{},
	)
	acc.processTraces(td)
	components, _ := acc.snapshot()
	if len(components) != 1 {
		t.Fatalf("expected 1 component, got %d", len(components))
	}
	if components[0].ExternalID != "suse-ai:product:application:my-app" {
		t.Errorf("unexpected externalId: %s", components[0].ExternalID)
	}
}

func TestDiscoverInferenceEngineAndUsesRelation(t *testing.T) {
	acc := newTopologyAccumulator("test-ns")
	td := makeTraces(
		map[string]string{"suse.ai.component.name": "open-webui", "suse.ai.component.type": "ui"},
		map[string]string{"gen_ai.provider.name": "ollama"},
	)
	acc.processTraces(td)
	components, relations := acc.snapshot()
	if len(components) != 2 {
		t.Fatalf("expected 2 components, got %d", len(components))
	}
	if len(relations) != 1 {
		t.Fatalf("expected 1 relation, got %d", len(relations))
	}
	r := relations[0]
	if r.Type.Name != "uses" {
		t.Errorf("unexpected relation type: %s", r.Type.Name)
	}
	if r.SourceID != "suse-ai:product:ui:open-webui" {
		t.Errorf("unexpected source: %s", r.SourceID)
	}
	if r.TargetID != "suse-ai:product:inference-engine:ollama" {
		t.Errorf("unexpected target: %s", r.TargetID)
	}
}

func TestDiscoverModelAndRunsRelation(t *testing.T) {
	acc := newTopologyAccumulator("test-ns")
	td := makeTraces(
		map[string]string{"suse.ai.component.name": "open-webui", "suse.ai.component.type": "ui"},
		map[string]string{"gen_ai.provider.name": "ollama", "gen_ai.request.model": "llama3.2"},
	)
	acc.processTraces(td)
	components, relations := acc.snapshot()
	if len(components) != 3 {
		t.Fatalf("expected 3 components, got %d", len(components))
	}
	if len(relations) != 2 {
		t.Fatalf("expected 2 relations, got %d", len(relations))
	}
	var runsRel *Relation
	for i := range relations {
		if relations[i].Type.Name == "runs" {
			runsRel = &relations[i]
			break
		}
	}
	if runsRel == nil {
		t.Fatal("expected a 'runs' relation")
	}
	if runsRel.SourceID != "suse-ai:product:inference-engine:ollama" {
		t.Errorf("unexpected runs source: %s", runsRel.SourceID)
	}
	if runsRel.TargetID != "suse-ai:product:llm-model:llama3.2" {
		t.Errorf("unexpected runs target: %s", runsRel.TargetID)
	}
}

func TestDiscoverVectorDB(t *testing.T) {
	acc := newTopologyAccumulator("test-ns")
	td := makeTraces(
		map[string]string{"suse.ai.component.name": "my-app", "suse.ai.component.type": "application"},
		map[string]string{"db.system": "milvus"},
	)
	acc.processTraces(td)
	components, relations := acc.snapshot()
	if len(components) != 2 {
		t.Fatalf("expected 2 components, got %d", len(components))
	}
	if len(relations) != 1 {
		t.Fatalf("expected 1 relation, got %d", len(relations))
	}
	if relations[0].TargetID != "suse-ai:product:vectordb:milvus" {
		t.Errorf("unexpected target: %s", relations[0].TargetID)
	}
}

func TestDiscoverSearchEngine(t *testing.T) {
	acc := newTopologyAccumulator("test-ns")
	td := makeTraces(
		map[string]string{"suse.ai.component.name": "my-app", "suse.ai.component.type": "application"},
		map[string]string{"db.system": "opensearch"},
	)
	acc.processTraces(td)
	components, relations := acc.snapshot()
	if len(components) != 2 {
		t.Fatalf("expected 2 components, got %d", len(components))
	}
	if relations[0].TargetID != "suse-ai:product:search-engine:opensearch" {
		t.Errorf("unexpected target: %s", relations[0].TargetID)
	}
}

func TestCaseInsensitiveDBSystem(t *testing.T) {
	acc := newTopologyAccumulator("test-ns")
	td := makeTraces(
		map[string]string{"suse.ai.component.name": "my-app", "suse.ai.component.type": "application"},
		map[string]string{"db.system": "Milvus"},
	)
	acc.processTraces(td)
	components, _ := acc.snapshot()
	found := false
	for _, c := range components {
		if c.ExternalID == "suse-ai:product:vectordb:milvus" {
			found = true
		}
	}
	if !found {
		t.Error("expected vectordb:milvus component (case-insensitive)")
	}
}

func TestSnapshotResetsAccumulator(t *testing.T) {
	acc := newTopologyAccumulator("test-ns")
	td := makeTraces(
		map[string]string{"suse.ai.component.name": "my-app", "suse.ai.component.type": "application"},
		map[string]string{"gen_ai.provider.name": "ollama"},
	)
	acc.processTraces(td)
	c1, r1 := acc.snapshot()
	if len(c1) != 2 || len(r1) != 1 {
		t.Fatalf("first snapshot: expected 2 components and 1 relation, got %d/%d", len(c1), len(r1))
	}
	c2, r2 := acc.snapshot()
	if len(c2) != 0 || len(r2) != 0 {
		t.Errorf("second snapshot: expected empty, got %d/%d", len(c2), len(r2))
	}
}

func TestModelWithoutProviderIsIgnored(t *testing.T) {
	acc := newTopologyAccumulator("test-ns")
	td := makeTraces(
		map[string]string{"suse.ai.component.name": "my-app", "suse.ai.component.type": "application"},
		map[string]string{"gen_ai.request.model": "llama3.2"},
	)
	acc.processTraces(td)
	components, relations := acc.snapshot()
	if len(components) != 1 {
		t.Errorf("expected 1 component (app only), got %d", len(components))
	}
	if len(relations) != 0 {
		t.Errorf("expected 0 relations, got %d", len(relations))
	}
}

func TestConcurrentProcessing(t *testing.T) {
	acc := newTopologyAccumulator("test-ns")
	var wg sync.WaitGroup
	for i := 0; i < 100; i++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			td := makeTraces(
				map[string]string{"suse.ai.component.name": "my-app", "suse.ai.component.type": "application"},
				map[string]string{"gen_ai.provider.name": "ollama"},
			)
			acc.processTraces(td)
		}()
	}
	wg.Wait()
	components, relations := acc.snapshot()
	if len(components) != 2 {
		t.Errorf("expected 2 components (no duplicates despite concurrency), got %d", len(components))
	}
	if len(relations) != 1 {
		t.Errorf("expected 1 relation (no duplicates despite concurrency), got %d", len(relations))
	}
}

func TestIdempotentProcessing(t *testing.T) {
	acc := newTopologyAccumulator("test-ns")
	td := makeTraces(
		map[string]string{"suse.ai.component.name": "my-app", "suse.ai.component.type": "application"},
		map[string]string{"gen_ai.provider.name": "ollama"},
	)
	acc.processTraces(td)
	acc.processTraces(td)
	components, relations := acc.snapshot()
	if len(components) != 2 {
		t.Errorf("expected 2 components (no duplicates), got %d", len(components))
	}
	if len(relations) != 1 {
		t.Errorf("expected 1 relation (no duplicates), got %d", len(relations))
	}
}
