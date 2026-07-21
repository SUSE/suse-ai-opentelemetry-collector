# Topology Retention (TTL) Design

**Date:** 2026-07-21
**Component:** `topologyexporter`

## Problem

In low-usage development clusters, topology connections (the lines that relate
components) disappear too quickly. Component identification works well; the issue
is relation (edge) detection being forgotten between sparse traces.

### Root cause

`topologyAccumulator.snapshot()` wipes both the `components` and `relations` maps
on every flush (default `flush_interval` = 60s). Each payload is sent as a full
snapshot (`start_snapshot: true, stop_snapshot: true`), so SUSE Observability
treats the payload as the *complete* current topology. Anything not observed in
the last flush window vanishes.

Components appear stable because a running app emits spans continuously and is
re-created every window. Relations flicker because relation-triggering spans (an
LLM call, a DB query) are sporadic — a single quiet window drops the edge.

## Goal

Retain observed topology (components and relations) for at least 15 minutes after
their last sighting. New components/relations still appear as soon as they are
observed. An entry only disappears once it has not been seen for the full
retention window.

The retention window applies uniformly to components and relations. This is
required for correctness: a retained edge whose endpoint component was already
wiped would be a dangling line. The user's phrasing ("not forget any components
for fifteen minutes") aligns with retaining both.

## Design

### 1. Config (`config.go`)

- Add field `Retention time.Duration` with `mapstructure:"retention"`.
- Default in `createDefaultConfig`: `15 * time.Minute`.
- `Validate`: `retention` must be `>= flush_interval`. A retention shorter than a
  flush window is meaningless. Return an error otherwise.

### 2. Accumulator data model (`topology.go`)

- Track a `lastSeen` timestamp per entry. Wrap map values:
  - `components map[string]componentEntry` where
    `componentEntry struct { component Component; lastSeen time.Time }`
  - `relations map[string]relationEntry` where
    `relationEntry struct { relation Relation; lastSeen time.Time }`
- The `Component` / `Relation` DTOs in `types.go` are unchanged.
- Add `retention time.Duration` field on the accumulator.
- Add `now func() time.Time` field, defaulting to `time.Now`, so tests can drive
  the clock deterministically instead of sleeping.
- `ensureComponent` / `ensureRelation` set `lastSeen = a.now()` on **both** create
  and re-observe, so every reaffirming span resets the TTL.

### 3. Flush behavior (`topology.go`, `exporter.go`)

- Replace the wipe in `snapshot()` with **evict-then-emit**:
  1. Compute cutoff = `a.now().Add(-a.retention)`.
  2. Delete any component/relation whose `lastSeen` is before the cutoff.
  3. Return the surviving entries (as `[]Component` / `[]Relation`).
  - The maps persist across flushes.
- `newTopologyAccumulator(namespace string, retention time.Duration)` receives the
  retention window.
- `newTopologyExporter` passes `cfg.Retention` through.
- Net effect: an edge observed once is re-sent every flush for at least the
  retention window after its last sighting, then falls out of the snapshot —
  which, under full-snapshot semantics, removes it from SUSE Observability.

### 4. Testing (`topology_test.go`)

- Replace `TestSnapshotResetsAccumulator` (its wipe-on-snapshot expectation is now
  invalid by design) with retention tests using the injected clock:
  - Entry observed, then snapshotted repeatedly with no new data: present before
    the window elapses, gone after.
  - Re-observing an entry within the window resets its TTL (survives longer).
  - A component kept alive only because a live relation references it does not
    dangle — both are retained under the same TTL, so this holds naturally.
- Existing discovery tests (single `processTraces` → immediate `snapshot`) remain
  valid, but calls to `newTopologyAccumulator` must pass a retention argument.

## Scope

- Files touched: `config.go`, `topology.go`, `exporter.go`, `topology_test.go`.
- No changes to DTOs / wire format / receiver client.
- No change to how SUSE Observability is called.

## Validation

Per project convention: build the distro first, then run `validate` with
`K8S_CLUSTER_NAME` set. Run `go test ./...` in `topologyexporter/`.
