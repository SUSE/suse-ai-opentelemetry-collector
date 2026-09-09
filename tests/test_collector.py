"""Exercise the shipped pipelines using a real collector and local endpoints."""

import argparse
import collections
import copy
import http.server
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[1]
OPTIONS = None


def free_port():
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def attributes(values):
    return [{"key": key, "value": {"stringValue": value}} for key, value in values.items()]


def unpack(items):
    return {item["key"]: next(iter(item["value"].values())) for item in items}


class MetricsHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        body = b'''# TYPE vllm:requests_total counter
vllm:requests_total{model_name="llama3"} 4
# TYPE vllm:latency_seconds histogram
vllm:latency_seconds_bucket{le="0.5",model_name="llama3"} 2
vllm:latency_seconds_bucket{le="+Inf",model_name="llama3"} 4
vllm:latency_seconds_sum{model_name="llama3"} 3
vllm:latency_seconds_count{model_name="llama3"} 4
'''
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


class CollectorIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="collector-test-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory = Path(cls.temp.name)
        cls.env = dict(os.environ, API_KEY="test-key", ELASTICSEARCH_PASSWORD="test-password",
                       K8S_CLUSTER_NAME="test-cluster", SUSE_AI_NAMESPACE="ai-test",
                       GPU_NAMESPACE="gpu-test", VLLM_METRICS_PORT="8000", OTEL_RESOURCE_ATTRIBUTES="")
        for key in ("MILVUS_METRICS_ENDPOINT", "QDRANT_METRICS_ENDPOINT", "ELASTICSEARCH_ENDPOINT"):
            cls.env.pop(key, None)
        cls.original = yaml.safe_load((ROOT / "collector-config.yaml").read_text())
        result = subprocess.run([OPTIONS.collector, "validate", "--config", str(ROOT / "collector-config.yaml")],
                                env=cls.env, capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)

        cls.servers = []
        for _ in range(2):
            server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), MetricsHandler)
            threading.Thread(target=server.serve_forever, daemon=True).start()
            cls.servers.append(server)
            cls.addClassCleanup(server.server_close)
            cls.addClassCleanup(server.shutdown)
        targets = [f"127.0.0.1:{s.server_port}" for s in cls.servers]
        cls.targets = targets
        cls.env["GPU_METRICS_PORT"] = str(cls.servers[0].server_port)
        config = copy.deepcopy(cls.original)
        cls.port, cls.es_port = free_port(), free_port()
        config["receivers"]["otlp"] = {"protocols": {"http": {"endpoint": f"127.0.0.1:{cls.port}"}}}
        config["receivers"]["otlp/elasticsearch-test"] = {"protocols": {"http": {"endpoint": f"127.0.0.1:{cls.es_port}"}}}
        config["receivers"].pop("jaeger")
        config["receivers"].pop("elasticsearch")
        for job in config["receivers"]["prometheus"]["config"]["scrape_configs"]:
            job["scrape_interval"], job["scrape_timeout"] = "1s", "1s"
            if "kubernetes_sd_configs" in job:
                job.pop("kubernetes_sd_configs")
                is_vllm = job["job_name"] == "vllm"
                labels = {"__meta_kubernetes_service_name": "my-vllm" if is_vllm else "nvidia-dcgm-exporter",
                          "__meta_kubernetes_service_port_number": "8000",
                          "__meta_kubernetes_namespace": "ai-test" if is_vllm else "gpu-test"}
                discovery = cls.directory / (job["job_name"] + ".json")
                discovery.write_text(json.dumps([{"targets": targets if is_vllm else targets[:1], "labels": labels}]))
                job["file_sd_configs"] = [{"files": [str(discovery)]}]
            else:
                for group in job["static_configs"]:
                    group["targets"] = targets[:1]
        # Kubernetes discovery/enrichment and the Elasticsearch API need a deployment.
        # Keep the real relabel rules and processor chains; only replace their inputs.
        config["processors"]["k8s_attributes"] = {"passthrough": True}
        config["extensions"]["health_check"]["endpoint"] = f"127.0.0.1:{free_port()}"
        cls.health = "http://" + config["extensions"]["health_check"]["endpoint"]
        config["service"]["telemetry"] = {"metrics": {"level": "none"}}
        config["exporters"] = {}
        cls.outputs = {}
        for name, pipeline in config["service"]["pipelines"].items():
            pipeline["receivers"] = [r for r in pipeline["receivers"] if r != "jaeger"]
            if name == "metrics/elasticsearch":
                pipeline["receivers"] = ["otlp/elasticsearch-test"]
            destination = "file/" + name.replace("/", "_")
            path = cls.directory / (name.replace("/", "_") + ".jsonl")
            cls.outputs[name] = path
            config["exporters"][destination] = {"path": str(path), "format": "json", "flush_interval": "100ms"}
            pipeline["exporters"] = [destination if e == "otlp" else e for e in pipeline["exporters"]]
        config_path = cls.directory / "config.yaml"
        config_path.write_text(yaml.safe_dump(config, sort_keys=False))
        cls.log_path = cls.directory / "collector.log"
        cls.log = cls.log_path.open("w")
        cls.addClassCleanup(cls.log.close)
        cls.process = subprocess.Popen([OPTIONS.collector, "--config", str(config_path)],
                                       env=cls.env, stdout=cls.log, stderr=cls.log)
        cls.addClassCleanup(cls.stop_collector)
        cls.wait_for(lambda: cls.healthy(), "collector health endpoint")

    def test_binary_version_matches_manifest(self):
        distribution = yaml.safe_load((ROOT / "builder-config.yaml").read_text())["dist"]
        self.assertTrue(distribution["version"])
        result = subprocess.run([OPTIONS.collector, "--version"], capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(result.stdout.strip(), f"{distribution['name']} version {distribution['version']}")

    @classmethod
    def healthy(cls):
        try:
            with urllib.request.urlopen(cls.health, timeout=0.3) as response:
                return response.status == 200
        except OSError:
            return False

    @classmethod
    def stop_collector(cls):
        cls.process.terminate()
        try:
            cls.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait()
            raise AssertionError("collector did not shut down within 10 seconds")

    @classmethod
    def wait_for(cls, predicate, description):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if cls.process.poll() is not None:
                raise AssertionError(cls.log_path.read_text())
            result = predicate()
            if result:
                return result
            time.sleep(0.1)
        raise AssertionError(f"Timed out waiting for {description}\n{cls.log_path.read_text()[-4000:]}")

    def send(self, signal, payload, port=None):
        request = urllib.request.Request(f"http://127.0.0.1:{port or self.port}/v1/{signal}",
                                         json.dumps(payload).encode(), {"Content-Type": "application/json"})
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)

    def resources(self, pipeline, key):
        path = self.outputs[pipeline]
        result = []
        if path.exists():
            for line in path.read_text().splitlines():
                try:
                    result.extend(json.loads(line).get(key, []))
                except json.JSONDecodeError:
                    pass  # A file-exporter write may still be in progress.
        return result

    def signal_resources(self, signal, key):
        return [row for pipeline in self.outputs if pipeline.split("/")[0] == signal
                for row in self.resources(pipeline, key)]

    def test_traces_keep_identity_and_aggregate_models(self):
        now = time.time_ns()
        spans = []
        for i, model in enumerate(["llama3", "llama3.1", "llama3", "claude"]):
            spans.append({"traceId": "1" * 32, "spanId": f"{i+1:016x}", "name": "chat", "kind": 3,
                          "startTimeUnixNano": str(now), "endTimeUnixNano": str(now + 1000000),
                          "attributes": attributes({"gen_ai.provider.name": "ollama" if i < 3 else "anthropic",
                                                    "gen_ai.request.model": model, "peer.service": "original-peer"})})
        original = {"service.name": "app", "service.namespace": "tenant-a", "host.name": "workload-host",
                    "gen_ai.system": "gateway", "gen_ai.provider.name": "resource-provider", "gen_ai.models": "existing"}
        resource = {"resource": {"attributes": attributes(original)}, "scopeSpans": [{"spans": spans}]}
        enriched = copy.deepcopy(resource)
        enriched["resource"]["attributes"] += attributes({"k8s.pod.uid": "pod-uid", "k8s.pod.name": "pod",
                                                         "k8s.node.name": "node", "k8s.namespace.name": "tenant-a"})
        for span in enriched["scopeSpans"][0]["spans"]:
            span["traceId"] = "2" * 32
        self.send("traces", {"resourceSpans": [resource, enriched]})
        self.wait_for(lambda: any(span["traceId"] == "2" * 32
                      for row in self.signal_resources("traces", "resourceSpans")
                      for scope in row["scopeSpans"] for span in scope["spans"]), "exported traces")
        rows = self.signal_resources("traces", "resourceSpans")
        seen = collections.Counter()
        for row in rows:
            relevant = [span for scope in row["scopeSpans"] for span in scope["spans"]
                        if span["traceId"] in ("1" * 32, "2" * 32)]
            if not relevant:
                continue
            values = unpack(row["resource"]["attributes"])
            self.assertEqual(values["gen_ai.models"], "existing,llama3,llama3.1,claude")
            for key, value in original.items():
                if key != "gen_ai.models":
                    self.assertEqual(values[key], value)
            for span in relevant:
                seen[span["traceId"], span["spanId"]] += 1
                self.assertEqual(unpack(span["attributes"])["peer.service"], "original-peer")
        self.assertEqual(len(seen), 8)
        self.assertEqual(set(seen.values()), {1})

    def test_metrics_are_normalized_once(self):
        data = {"resourceMetrics": [{"resource": {"attributes": attributes({"service.name": "metric-app", "service.namespace": "tenant-b"})},
                 "scopeMetrics": [{"metrics": [{"name": "gen_ai.client.token.usage", "gauge": {"dataPoints": [
                     {"attributes": attributes({"GenAiSystem": "ollama", "GenAiRequestModel": "legacy", "gen_ai.request.model": "current"}),
                      "timeUnixNano": str(time.time_ns()), "asInt": "4"}]}}]}]}]}
        self.send("metrics", data)
        self.wait_for(lambda: self.resources("metrics", "resourceMetrics"), "OTLP metrics")
        rows = self.signal_resources("metrics", "resourceMetrics")
        points = []
        for row in rows:
            for scope in row["scopeMetrics"]:
                for metric in scope["metrics"]:
                    if metric["name"] == "gen_ai.client.token.usage":
                        values = unpack(row["resource"]["attributes"])
                        self.assertEqual(values["service.name"], "metric-app")
                        self.assertEqual(values["service.namespace"], "tenant-b")
                        self.assertEqual(values["gen_ai.provider.name"], "ollama")
                        self.assertEqual(values["gen_ai.models"], "current")
                        points.extend(metric["gauge"]["dataPoints"])
        self.assertEqual(len(points), 1)
        self.assertEqual(unpack(points[0]["attributes"])["gen_ai.request.model"], "current")

    def test_span_legacy_attributes_preserve_current_values(self):
        now = time.time_ns()
        self.send("traces", {"resourceSpans": [{"resource": {"attributes": attributes({"service.name": "legacy-app", "gen_ai.system": "litellm"})},
            "scopeSpans": [{"spans": [{"traceId": "3" * 32, "spanId": "0000000000000001", "name": "chat", "kind": 3,
                "startTimeUnixNano": str(now), "endTimeUnixNano": str(now + 1000000),
                "attributes": attributes({"GenAiSystem": "ollama", "gen_ai.provider.name": "openai",
                    "GenAiRequestModel": "legacy-model", "gen_ai.request.model": "current-model",
                    "GenAiOperationName": "legacy-operation", "gen_ai.operation.name": "chat"})}]}]}]})
        def legacy_resource():
            return next((row for row in self.resources("traces", "resourceSpans")
                         if unpack(row["resource"]["attributes"])["service.name"] == "legacy-app"), None)
        row = self.wait_for(legacy_resource, "legacy trace normalization")
        values = unpack(row["resource"]["attributes"])
        self.assertEqual(values["gen_ai.system"], "litellm")
        self.assertEqual(values["gen_ai.provider.name"], "openai")
        self.assertEqual(values["gen_ai.models"], "current-model")
        span = unpack(row["scopeSpans"][0]["spans"][0]["attributes"])
        self.assertEqual(span["gen_ai.operation.name"], "chat")

    def test_scraper_resources_keep_target_identity(self):
        def scrape_resources():
            rows = self.resources("metrics/prometheus", "resourceMetrics")
            names = {unpack(row["resource"]["attributes"]).get("service.name") for row in rows}
            return rows if names == {"my-vllm", "milvus", "qdrant", "nvidia-dcgm-exporter"} else None
        rows = self.wait_for(scrape_resources, "all scraper jobs")
        vllm_instances = set()
        histogram_seen = False
        for row in rows:
            values = unpack(row["resource"]["attributes"])
            name = values["service.name"]
            self.assertEqual(values["service.namespace"], "gpu-test" if name == "nvidia-dcgm-exporter" else "ai-test")
            if name == "my-vllm":
                self.assertEqual(values["gen_ai.system"], "vllm")
                self.assertEqual(values["gen_ai.provider.name"], "vllm")
                vllm_instances.add(values["service.instance.id"])
            elif name in ("milvus", "qdrant"):
                self.assertEqual(values["db.system"], name)
                self.assertEqual(values["db.system.name"], name)
            else:
                self.assertEqual(values["hw.type"], "gpu")
                self.assertNotIn("gen_ai.system", values)
            for scope in row["scopeMetrics"]:
                for metric in scope["metrics"]:
                    for kind in ("gauge", "sum", "histogram"):
                        for point in metric.get(kind, {}).get("dataPoints", []):
                            labels = unpack(point.get("attributes", []))
                            self.assertEqual(labels["service_name"], name)
                            if name == "my-vllm" and "model_name" in labels:
                                self.assertEqual(labels["gen_ai.request.model"], "llama3")
                    if name == "my-vllm" and metric["name"].startswith("vllm:") and "histogram" in metric:
                        histogram_seen = True
                        self.assertEqual(int(metric["histogram"]["dataPoints"][0]["count"]), 4)
        self.assertEqual(vllm_instances, set(self.targets))
        self.assertTrue(histogram_seen, "native latency histograms must survive normalization")

    def test_logs_preserve_source(self):
        original = {"service.name": "log-app", "service.namespace": "tenant-c", "host.name": "log-host"}
        self.send("logs", {"resourceLogs": [{"resource": {"attributes": attributes(original)}, "scopeLogs": [
            {"logRecords": [{"timeUnixNano": str(time.time_ns()), "body": {"stringValue": "hello"}}]}]}]})
        rows = self.wait_for(lambda: self.resources("logs", "resourceLogs"), "logs")
        self.assertEqual(len(rows), 1)
        values = unpack(rows[0]["resource"]["attributes"])
        for key, value in original.items():
            self.assertEqual(values[key], value)

    def test_elasticsearch_resource_identity(self):
        self.send("metrics", {"resourceMetrics": [{"resource": {"attributes": attributes({"elasticsearch.node.name": "node-a"})},
            "scopeMetrics": [{"metrics": [{"name": "elasticsearch.node.fs.disk.total", "gauge": {"dataPoints": [
                {"timeUnixNano": str(time.time_ns()), "asInt": "1024"}]}}]}]}]}, port=self.es_port)
        rows = self.wait_for(lambda: self.resources("metrics/elasticsearch", "resourceMetrics"), "Elasticsearch resource")
        values = unpack(rows[0]["resource"]["attributes"])
        self.assertEqual(values["service.name"], "opensearch")
        self.assertEqual(values["service.namespace"], "ai-test")
        self.assertEqual(values["db.system"], "opensearch")
        self.assertEqual(values["db.system.name"], "opensearch")
        self.assertEqual(values["elasticsearch.node.name"], "node-a")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--collector", required=True, type=lambda path: str(Path(path).resolve()))
    OPTIONS, remaining = parser.parse_known_args()
    unittest.main(argv=[__file__, *remaining], verbosity=2)
