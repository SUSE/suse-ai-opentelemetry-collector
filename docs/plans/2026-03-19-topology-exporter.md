# Topology Exporter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a custom OTel exporter that discovers topology from GenAI/DB spans and pushes components + relations to SUSE Observability's receiver API.

**Architecture:** The exporter consumes traces, accumulates topology in memory (components keyed by externalId, relations keyed by sourceId-->targetId), and flushes a full snapshot to `/receiver/stsAgent/intake` on a configurable interval. A companion sync in the StackPack consumes the topology from the Kafka topic.

**Tech Stack:** Go 1.24, OpenTelemetry Collector SDK v0.142.0 (`configtls`, `exporterhelper`), SUSE Observability receiver API, StackPack STY/Handlebars templates.

**Spec:** `docs/specs/2026-03-19-topology-exporter-design.md`

**Two repos involved:**
- `suse-ai-opentelemetry-collector` — the custom OTel collector (Go exporter module)
- `suse-ai-observability-extension` — the StackPack (sync config, templates)

---

## File Structure

### New files in `suse-ai-opentelemetry-collector/topologyexporter/`

| File | Responsibility |
|------|---------------|
| `types.go` | Receiver API DTOs: Component, Relation, Topology, Payload |
| `config.go` | Config struct (embeds `configtls.ClientConfig`), defaults, Validate() |
| `factory.go` | OTel factory: NewFactory(), createDefaultConfig(), createTracesExporter() |
| `topology.go` | Thread-safe accumulator: processSpan(), snapshot(), component/relation builders |
| `topology_test.go` | Unit tests for topology discovery from mock spans |
| `receiver_client.go` | HTTP client: send topology snapshots to receiver API |
| `receiver_client_test.go` | Unit tests: payload serialization, HTTP calls against mock server |
| `exporter.go` | Main exporter: start(), shutdown(), pushTraces(), flush loop |
| `exporter_test.go` | Integration test: full pipeline from traces to HTTP payload |
| `go.mod` | Go module definition |

### New files in `suse-ai-observability-extension/stackpack/`

| File | Responsibility |
|------|---------------|
| `suse-ai/provisioning/templates/sync/topology-sync-component-template.json.handlebars` | Component template using `resolveOrCreate` for type/layer |
| `suse-ai/provisioning/templates/sync/topology-sync-id-extractor.groovy` | Passthrough ID extractor (like autosync) |

### Modified files in `suse-ai-observability-extension/stackpack/`

| File | Change |
|------|--------|
| `suse-ai/provisioning/templates/synchronization.sty` | Add DataSource, Sync, ID extractors, templates for topology sync |

### Modified files in `suse-ai-opentelemetry-collector/`

| File | Change |
|------|--------|
| `builder-config.yaml` | Add topologyexporter as local module |

---

## Task 1: Receiver API Types

**Files:**
- Create: `suse-ai-opentelemetry-collector/topologyexporter/types.go`

These are the DTOs matching the SUSE Observability receiver API format. Ported from the v1.5.0 sidecar (`stackstate/receiver/types.go`), simplified to only what the topology exporter needs.

- [ ] **Step 1: Create the Go module**

```bash
cd /home/thbertoldi/suse/suse-ai-opentelemetry-collector
mkdir -p topologyexporter
```

Create `topologyexporter/go.mod`:
```
module github.com/suse/suse-ai-opentelemetry-collector/topologyexporter

go 1.24.0

require (
    go.opentelemetry.io/collector/component v1.48.0
    go.opentelemetry.io/collector/config/configtls v1.48.0
    go.opentelemetry.io/collector/consumer v1.48.0
    go.opentelemetry.io/collector/exporter v0.142.0
    go.opentelemetry.io/collector/pdata v1.48.0
)
```

Run: `cd topologyexporter && go mod tidy`

- [ ] **Step 2: Write types.go**

```go
package topologyexporter

import (
    "time"
)

// Receiver API DTOs for SUSE Observability /receiver/stsAgent/intake

type Type struct {
    Name string `json:"name"`
}

type ComponentData struct {
    Name        string                 `json:"name"`
    Layer       string                 `json:"layer"`
    Domain      string                 `json:"domain"`
    Environment string                 `json:"environment,omitempty"`
    Labels      []string               `json:"labels"`
    Identifiers []string               `json:"identifiers"`
}

type Component struct {
    ExternalID string        `json:"externalId"`
    Type       Type          `json:"type"`
    Data       ComponentData `json:"data"`
}

type Relation struct {
    ExternalID string `json:"externalId"`
    SourceID   string `json:"sourceId"`
    TargetID   string `json:"targetId"`
    Type       Type   `json:"type"`
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
}

type Payload struct {
    CollectionTimestamp int64             `json:"collection_timestamp"`
    InternalHostname    string            `json:"internalHostname"`
    Topologies          []Topology        `json:"topologies"`
    Events              map[string][]any  `json:"events"`
    Metrics             []any             `json:"metrics"`
    ServiceChecks       []any             `json:"service_checks"`
    Health              []any             `json:"health"`
}

func NewPayload(instance Instance, components []Component, relations []Relation) *Payload {
    return &Payload{
        CollectionTimestamp: time.Now().Unix(),
        InternalHostname:    "suse-ai-opentelemetry-collector",
        Topologies: []Topology{{
            StartSnapshot: true,
            StopSnapshot:  true,
            Instance:      instance,
            Components:    components,
            Relations:     relations,
        }},
        Events:        make(map[string][]any),
        Metrics:       []any{},
        ServiceChecks: []any{},
        Health:        []any{},
    }
}
```

- [ ] **Step 3: Verify it compiles**

Run: `cd /home/thbertoldi/suse/suse-ai-opentelemetry-collector/topologyexporter && go build ./...`
Expected: clean build, no errors.

- [ ] **Step 4: Commit**

```bash
git add topologyexporter/go.mod topologyexporter/go.sum topologyexporter/types.go
git commit -m "feat(topologyexporter): add receiver API types"
```

---

## Task 2: Config

**Files:**
- Create: `suse-ai-opentelemetry-collector/topologyexporter/config.go`

- [ ] **Step 1: Write config.go**

```go
package topologyexporter

import (
    "errors"
    "time"

    "go.opentelemetry.io/collector/config/configtls"
)

type Config struct {
    TLS           configtls.ClientConfig `mapstructure:"tls"`
    Endpoint      string                 `mapstructure:"endpoint"`
    APIKey        string                 `mapstructure:"api_key"`
    InstanceType  string                 `mapstructure:"instance_type"`
    InstanceURL   string                 `mapstructure:"instance_url"`
    FlushInterval time.Duration          `mapstructure:"flush_interval"`
    Namespace     string                 `mapstructure:"namespace"`
}

func createDefaultConfig() *Config {
    return &Config{
        InstanceType:  "suse-ai",
        InstanceURL:   "local",
        FlushInterval: 60 * time.Second,
    }
}

func (cfg *Config) Validate() error {
    if cfg.Endpoint == "" {
        return errors.New("endpoint is required")
    }
    if cfg.APIKey == "" {
        return errors.New("api_key is required")
    }
    if cfg.FlushInterval < 10*time.Second {
        return errors.New("flush_interval must be >= 10s")
    }
    return nil
}
```

- [ ] **Step 2: Verify it compiles**

Run: `cd /home/thbertoldi/suse/suse-ai-opentelemetry-collector/topologyexporter && go build ./...`
Expected: clean build.

- [ ] **Step 3: Commit**

```bash
git add topologyexporter/config.go
git commit -m "feat(topologyexporter): add config with TLS and validation"
```

---

## Task 3: Topology Accumulator

**Files:**
- Create: `suse-ai-opentelemetry-collector/topologyexporter/topology.go`
- Create: `suse-ai-opentelemetry-collector/topologyexporter/topology_test.go`

This is the core logic — discovering components/relations from span attributes.

- [ ] **Step 1: Write the failing tests**

Create `topologyexporter/topology_test.go`. Tests cover:
1. Skip spans without `suse.ai.component.name`
2. Discover app component from resource attributes
3. Default `suse.ai.component.type` to "application" when missing
4. Discover inference-engine from `gen_ai.provider.name` + create `uses` relation
5. Discover llm-model from `gen_ai.request.model` + create `runs` relation
6. Discover vectordb from `db.system=milvus` + create `uses` relation
7. Discover search-engine from `db.system=opensearch` + create `uses` relation
8. Case-insensitive `db.system` matching
9. `snapshot()` returns accumulated data and resets
10. Idempotent — same span twice doesn't duplicate components/relations

```go
package topologyexporter

import (
    "sync"
    "testing"

    "go.opentelemetry.io/collector/pdata/ptrace"
)

// helper to create a span with resource and span attributes
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
    // Should have 2 components: ui + inference-engine
    if len(components) != 2 {
        t.Fatalf("expected 2 components, got %d", len(components))
    }
    // Should have 1 relation: ui -> inference-engine (uses)
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
    // 3 components: ui + inference-engine + llm-model
    if len(components) != 3 {
        t.Fatalf("expected 3 components, got %d", len(components))
    }
    // 2 relations: ui->inference-engine (uses), inference-engine->model (runs)
    if len(relations) != 2 {
        t.Fatalf("expected 2 relations, got %d", len(relations))
    }
    // Find the runs relation
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
    // Second snapshot should be empty
    c2, r2 := acc.snapshot()
    if len(c2) != 0 || len(r2) != 0 {
        t.Errorf("second snapshot: expected empty, got %d/%d", len(c2), len(r2))
    }
}

func TestModelWithoutProviderIsIgnored(t *testing.T) {
    acc := newTopologyAccumulator("test-ns")
    td := makeTraces(
        map[string]string{"suse.ai.component.name": "my-app", "suse.ai.component.type": "application"},
        map[string]string{"gen_ai.request.model": "llama3.2"}, // no provider
    )
    acc.processTraces(td)
    components, relations := acc.snapshot()
    // Only the app component, no model (models require a provider)
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
    acc.processTraces(td) // same span again
    components, relations := acc.snapshot()
    if len(components) != 2 {
        t.Errorf("expected 2 components (no duplicates), got %d", len(components))
    }
    if len(relations) != 1 {
        t.Errorf("expected 1 relation (no duplicates), got %d", len(relations))
    }
}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/thbertoldi/suse/suse-ai-opentelemetry-collector/topologyexporter && go test ./... -v`
Expected: FAIL — `newTopologyAccumulator` undefined.

- [ ] **Step 3: Write topology.go**

```go
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

        componentName, ok := resource.Attributes().Get("suse.ai.component.name")
        if !ok {
            continue
        }
        appName := componentName.Str()

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

    // GenAI provider discovery
    if provider, ok := attrs.Get("gen_ai.provider.name"); ok {
        providerName := provider.Str()
        providerID := a.ensureComponent(providerName, "inference-engine")
        a.ensureRelation(appID, providerID, "uses")

        // Model discovery
        if model, ok := attrs.Get("gen_ai.request.model"); ok {
            modelName := model.Str()
            modelID := a.ensureComponent(modelName, "llm-model")
            a.ensureRelation(providerID, modelID, "runs")
        }
    }

    // DB system discovery
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
                Name:        name,
                Layer:       layerFor(componentType),
                Domain:      "SUSE AI",
                Labels:      labels,
                Identifiers: []string{externalID},
            },
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

    // Reset
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/thbertoldi/suse/suse-ai-opentelemetry-collector/topologyexporter && go test ./... -v`
Expected: all 12 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add topologyexporter/topology.go topologyexporter/topology_test.go
git commit -m "feat(topologyexporter): add topology accumulator with discovery logic"
```

---

## Task 4: Receiver Client

**Files:**
- Create: `suse-ai-opentelemetry-collector/topologyexporter/receiver_client.go`
- Create: `suse-ai-opentelemetry-collector/topologyexporter/receiver_client_test.go`

- [ ] **Step 1: Write the failing test**

Create `topologyexporter/receiver_client_test.go`:

```go
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /home/thbertoldi/suse/suse-ai-opentelemetry-collector/topologyexporter && go test ./... -run TestReceiverClient -v`
Expected: FAIL — `newReceiverClient` undefined.

- [ ] **Step 3: Write receiver_client.go**

```go
package topologyexporter

import (
    "bytes"
    "encoding/json"
    "fmt"
    "log/slog"
    "net/http"
    "strings"
)

const receiverEndpoint = "receiver/stsAgent/intake"

type receiverClient struct {
    endpoint   string
    apiKey     string
    instance   Instance
    httpClient *http.Client
}

func newReceiverClient(endpoint, apiKey string, instance Instance, httpClient *http.Client) *receiverClient {
    return &receiverClient{
        endpoint:   strings.TrimSuffix(endpoint, "/"),
        apiKey:     apiKey,
        instance:   instance,
        httpClient: httpClient,
    }
}

func (c *receiverClient) send(components []Component, relations []Relation) error {
    payload := NewPayload(c.instance, components, relations)

    body, err := json.Marshal(payload)
    if err != nil {
        return fmt.Errorf("failed to marshal payload: %w", err)
    }

    url := fmt.Sprintf("%s/%s?api_key=%s", c.endpoint, receiverEndpoint, c.apiKey)
    req, err := http.NewRequest(http.MethodPost, url, bytes.NewReader(body))
    if err != nil {
        return fmt.Errorf("failed to create request: %w", err)
    }
    req.Header.Set("Content-Type", "application/json")

    resp, err := c.httpClient.Do(req)
    if err != nil {
        return fmt.Errorf("failed to send topology: %w", err)
    }
    defer resp.Body.Close()

    if resp.StatusCode >= 400 {
        return fmt.Errorf("receiver returned status %d", resp.StatusCode)
    }

    slog.Info("topology sent",
        "components", len(components),
        "relations", len(relations),
        "status", resp.StatusCode,
    )
    return nil
}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /home/thbertoldi/suse/suse-ai-opentelemetry-collector/topologyexporter && go test ./... -run TestReceiverClient -v`
Expected: both tests PASS.

- [ ] **Step 5: Commit**

```bash
git add topologyexporter/receiver_client.go topologyexporter/receiver_client_test.go
git commit -m "feat(topologyexporter): add receiver API client with tests"
```

---

## Task 5: Exporter + Factory

**Files:**
- Create: `suse-ai-opentelemetry-collector/topologyexporter/exporter.go`
- Create: `suse-ai-opentelemetry-collector/topologyexporter/factory.go`
- Create: `suse-ai-opentelemetry-collector/topologyexporter/exporter_test.go`

- [ ] **Step 1: Write the failing integration test**

Create `topologyexporter/exporter_test.go`:

```go
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

    "go.opentelemetry.io/collector/component"
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
    cfg.FlushInterval = 100 * time.Millisecond // fast flush for testing
    cfg.Namespace = "suse-ai"

    exp := newTopologyExporter(cfg)

    // Start
    err := exp.start(context.Background(), componenttest.NewNopHost())
    if err != nil {
        t.Fatalf("start failed: %v", err)
    }

    // Push traces
    td := makeTraces(
        map[string]string{"suse.ai.component.name": "open-webui", "suse.ai.component.type": "ui"},
        map[string]string{"gen_ai.provider.name": "ollama", "gen_ai.request.model": "llama3.2"},
    )
    err = exp.pushTraces(context.Background(), td)
    if err != nil {
        t.Fatalf("pushTraces failed: %v", err)
    }

    // Wait for flush
    time.Sleep(300 * time.Millisecond)

    // Shutdown
    err = exp.shutdown(context.Background())
    if err != nil {
        t.Fatalf("shutdown failed: %v", err)
    }

    mu.Lock()
    defer mu.Unlock()

    if len(receivedPayloads) == 0 {
        t.Fatal("expected at least 1 payload")
    }

    // Check the first non-empty payload
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
```

Note: This test overrides `FlushInterval` to 100ms (below the 10s `Validate()` minimum) — since we call `newTopologyExporter` directly (not through the OTel framework), `Validate()` is not called. This is intentional for testing.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd /home/thbertoldi/suse/suse-ai-opentelemetry-collector/topologyexporter && go test ./... -run TestExporterFullPipeline -v`
Expected: FAIL — `newTopologyExporter` undefined.

- [ ] **Step 3: Write exporter.go**

```go
package topologyexporter

import (
    "context"
    "log/slog"
    "net/http"
    "time"

    "go.opentelemetry.io/collector/component"
    "go.opentelemetry.io/collector/pdata/ptrace"
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
        accumulator: newTopologyAccumulator(cfg.Namespace),
        done:        make(chan struct{}),
    }
}

func (e *topologyExporter) start(ctx context.Context, host component.Host) error {
    // Build TLS config
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
        Type: e.cfg.InstanceType,
        URL:  e.cfg.InstanceURL,
    }
    e.client = newReceiverClient(e.cfg.Endpoint, e.cfg.APIKey, instance, httpClient)

    // Start flush loop
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
    // Final flush
    e.flush()
    return nil
}
```

Note: The `configtls.ClientConfig.LoadTLSConfig()` returns `*tls.Config` but we only pass it to `transport.TLSClientConfig`, so no direct `crypto/tls` import is needed.

- [ ] **Step 4: Write factory.go**

```go
package topologyexporter

import (
    "context"

    "go.opentelemetry.io/collector/component"
    "go.opentelemetry.io/collector/consumer"
    "go.opentelemetry.io/collector/exporter"
    "go.opentelemetry.io/collector/exporter/exporterhelper"
)

const typeStr = "topology"

func NewFactory() exporter.Factory {
    return exporter.NewFactory(
        component.MustNewType(typeStr),
        func() component.Config { return createDefaultConfig() },
        exporter.WithTraces(createTracesExporter, component.StabilityLevelAlpha),
    )
}

func createTracesExporter(
    ctx context.Context,
    set exporter.Settings,
    cfg component.Config,
) (exporter.Traces, error) {
    oCfg := cfg.(*Config)
    exp := newTopologyExporter(oCfg)

    return exporterhelper.NewTraces(
        ctx,
        set,
        cfg,
        exp.pushTraces,
        exporterhelper.WithCapabilities(consumer.Capabilities{MutatesData: false}),
        exporterhelper.WithStart(exp.start),
        exporterhelper.WithShutdown(exp.shutdown),
    )
}
```

- [ ] **Step 5: Run all tests**

Run: `cd /home/thbertoldi/suse/suse-ai-opentelemetry-collector/topologyexporter && go test ./... -v`
Expected: all tests PASS (12 topology tests + 2 receiver client tests + 1 integration test).

- [ ] **Step 6: Commit**

```bash
git add topologyexporter/exporter.go topologyexporter/factory.go topologyexporter/exporter_test.go
git commit -m "feat(topologyexporter): add exporter with factory and flush loop"
```

---

## Task 6: Register in Builder

**Files:**
- Modify: `suse-ai-opentelemetry-collector/builder-config.yaml`

- [ ] **Step 1: Add the topology exporter to builder-config.yaml**

Add under the `exporters:` section:

```yaml
  - gomod: github.com/suse/suse-ai-opentelemetry-collector/topologyexporter v0.0.0
    path: ./topologyexporter
```

The `path: ./topologyexporter` directive tells the builder to use the local module instead of fetching from a registry.

- [ ] **Step 2: Rebuild the collector**

Run: `cd /home/thbertoldi/suse/suse-ai-opentelemetry-collector && go run go.opentelemetry.io/collector/cmd/builder@v0.142.0 --config builder-config.yaml`
Expected: build succeeds, the `topology` exporter is registered.

If the build fails due to module resolution, you may need to add a `replace` directive in the generated `go.mod` or adjust the `gomod` path. The builder docs say local modules use `path:` to override.

- [ ] **Step 3: Commit**

```bash
git add builder-config.yaml
git commit -m "feat: register topology exporter in collector builder"
```

---

## Task 7: StackPack Topology Sync

**Files:**
- Create: `suse-ai-observability-extension/stackpack/suse-ai/provisioning/templates/sync/topology-sync-component-template.json.handlebars`
- Create: `suse-ai-observability-extension/stackpack/suse-ai/provisioning/templates/sync/topology-sync-id-extractor.groovy`
- Modify: `suse-ai-observability-extension/stackpack/suse-ai/provisioning/templates/synchronization.sty`

This task is in the `suse-ai-observability-extension` repo.

- [ ] **Step 1: Create the passthrough ID extractor**

Create `stackpack/suse-ai/provisioning/templates/sync/topology-sync-id-extractor.groovy`:

```groovy
// Passthrough ID extractor for the topology sync.
// Uses externalId as-is and reads identifiers from data.identifiers.

element = topologyElement.asReadonlyMap()

externalId = element["externalId"]
type = element["typeName"].toLowerCase()
data = element["data"]

identifiers = new HashSet()

if (data.containsKey("identifiers") && data["identifiers"] instanceof List) {
    data["identifiers"].each { id ->
        identifiers.add(id)
    }
}

return Sts.createId(externalId, identifiers, type)
```

- [ ] **Step 2: Create the topology sync component template**

Create `stackpack/suse-ai/provisioning/templates/sync/topology-sync-component-template.json.handlebars`:

```handlebars
{
  "_type": "Component",
  "labels": [
    \{{#if element.data.labels \}}
        \{{# join element.data.labels "," "" "" \}}
        {
            "_type": "Label",
            "name": "\{{ this \}}"
        }
        \{{/ join \}}
    \{{/if\}}
  ],
  "name": "\{{#if element.data.name\}}\{{ element.data.name \}}\{{else\}}\{{ element.externalId \}}\{{/if\}}",
  "type": \{{ getOrCreate (identifier "urn:stackpack:suse-ai:shared" "ComponentType" element.type.name) (identifier "urn:system:auto" "ComponentType" element.type.name) (concat "Type=ComponentType;Name=" element.type.name) \}},
  "layer": \{{ getOrCreate (identifier "urn:stackpack:common" "Layer" element.data.layer) (identifier "urn:system:auto" "Layer" element.data.layer) (concat "Type=Layer;Name=" element.data.layer) \}},
  "domain": \{{ getOrCreate (identifier "urn:stackpack:suse-ai:shared" "Domain" element.data.domain) (identifier "urn:system:auto" "Domain" element.data.domain) (concat "Type=Domain;Name=" element.data.domain) \}},
  "environments": [
    \{{ get "urn:stackpack:common:environment:production" \}}
  ]
}
```

Note: This uses the same `getOrCreate` + `identifier` pattern as the existing SUSE AI component template. The type URN uses `urn:stackpack:suse-ai:shared` as the primary namespace (matching existing component types). The layer URN uses `urn:stackpack:common` since layers like "Services" and "Applications" are defined in the common StackPack.

- [ ] **Step 3: Add the topology sync to synchronization.sty**

Append the following to `stackpack/suse-ai/provisioning/templates/synchronization.sty`. Reference existing patterns in the file (DataSource at -1000, Sync at -1004/-1007).

```yaml
  # --- Topology Sync (consumes topology from the topology exporter) ---

  - _type: DataSource
    name: "SUSE AI Topology Exporter"
    identifier: "urn:stackpack:suse-ai:shared:data-source:suse-ai-topology"
    pluginId: Sts
    config:
      autoExpireElements: true
      expireElementsAfter: 300000
      _type: Sts.StsTopologyDataSourceConfig
      id: -1118
      supportedWindowingMethods: []
      integrationType: suse-ai
      supportedDataTypes:
        - TOPOLOGY_ELEMENTS
      topic: sts_topo_suse-ai_local
    extTopology:
      _type: ExtTopology
      dataSource: -1108
      id: -1109
      settings:
        _type: TopologySyncSettings
        maxBatchesPerSecond: 5
        id: -1110
        maxBatchSize: 200
    id: -1108
    uiRequestTimeout: 15000

  - _type: Sync
    name: "SUSE AI Topology"
    identifier: "urn:stackpack:suse-ai:shared:sync:suse-ai-topology"
    relationActions: []
    extTopology: -1109
    topologyDataQuery:
      _type: Sts.StsTopologyElementsQuery
      componentIdExtractorFunction: -1112
      relationIdExtractorFunction: -1113
      id: -1119
      consumerOffsetStartAtEarliest: true
    id: -1111
    defaultComponentAction:
      _type: SyncActionCreateComponent
      templateFunction: -1114
      id: -1116
      mergeStrategy: MergePreferTheirs
      type: default_component_mapping
    componentActions: []
    defaultRelationAction:
      _type: SyncActionCreateRelation
      templateFunction: -1103
      id: -1117
      mergeStrategy: MergePreferTheirs
      type: default_relation_mapping

  - _type: IdExtractorFunction
    id: -1112
    identifier: urn:stackpack:suse-ai:shared:id-extractor-function:topology-sync-component-id-extractor
    name: Topology Sync Component ID extractor
    parameters:
      - _type: Parameter
        multiple: false
        name: topologyElement
        required: true
        system: true
        type: STRUCT_TYPE
    groovyScript: "{{ include "templates/sync/topology-sync-id-extractor.groovy" }}"

  - _type: IdExtractorFunction
    id: -1113
    identifier: urn:stackpack:suse-ai:shared:id-extractor-function:topology-sync-relation-id-extractor
    name: Topology Sync Relation ID extractor
    parameters:
      - _type: Parameter
        multiple: false
        name: topologyElement
        required: true
        system: true
        type: STRUCT_TYPE
    groovyScript: |
      element = topologyElement.asReadonlyMap()
      externalId = element["externalId"]
      type = element["typeName"].toLowerCase()
      return Sts.createId(externalId, new HashSet(), type)

  - _type: ComponentTemplateFunction
    handlebarsTemplate: "{{ include "templates/sync/topology-sync-component-template.json.handlebars" }}"
    id: -1114
    identifier: urn:stackpack:suse-ai:shared:component-template-function:topology-sync-component
    name: Topology Sync Component Template
    parameters:
      - _type: Parameter
        multiple: false
        name: element
        required: true
        system: false
        type: STRUCT_TYPE
```

Note: The relation template reuses the existing one (-1103) since the relation JSON format is the same (`sourceExternalId`, `targetExternalId`, `type.name`).

- [ ] **Step 4: Commit**

```bash
cd /home/thbertoldi/suse/suse-ai-observability-extension
git add stackpack/suse-ai/provisioning/templates/sync/topology-sync-id-extractor.groovy
git add stackpack/suse-ai/provisioning/templates/sync/topology-sync-component-template.json.handlebars
git add stackpack/suse-ai/provisioning/templates/synchronization.sty
git commit -m "feat: add topology sync for exporter-pushed relations"
```

---

## Task 8: Update Knowledge Files

**Files:**
- Modify: `suse-ai-observability-extension/knowledge/AUTOSYNC_STACKPACK.md`
- Modify: `suse-ai-observability-extension/knowledge/GENAI_TOPOLOGY_INFERENCE.md`

- [ ] **Step 1: Update GENAI_TOPOLOGY_INFERENCE.md**

Add a new section before "Limitations" describing the topology exporter approach as the solution for product-to-product relations.

- [ ] **Step 2: Update AUTOSYNC_STACKPACK.md**

Update the "Current Decision" section to reference the topology exporter as the chosen solution.

- [ ] **Step 3: Update MEMORY.md**

Update the ID allocation ranges to include -1108 to -1120 for the topology sync, and add a note about the topology exporter architecture.

- [ ] **Step 4: Commit**

```bash
cd /home/thbertoldi/suse/suse-ai-observability-extension
git add knowledge/AUTOSYNC_STACKPACK.md knowledge/GENAI_TOPOLOGY_INFERENCE.md
git commit -m "docs: update knowledge files with topology exporter approach"
```
