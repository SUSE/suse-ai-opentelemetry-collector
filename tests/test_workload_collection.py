"""Run real discovery, probes and identity processors against a local K8s API fixture."""

import argparse
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
from urllib.parse import parse_qs, urlsplit

import yaml

ROOT = Path(__file__).resolve().parents[1]
OPTIONS = None


def unpack(items):
    return {item['key']: next(iter(item['value'].values())) for item in items}


def pod(name, namespace, product, address, port, *, component=None, port_name='http'):
    labels = {'app.kubernetes.io/name': product}
    if component:
        labels['app.kubernetes.io/component'] = component
    return {
        'apiVersion': 'v1', 'kind': 'Pod',
        'metadata': {'name': name, 'namespace': namespace, 'uid': f'{namespace}-{name}-uid',
                     'resourceVersion': '1', 'labels': labels},
        'spec': {'nodeName': f'{namespace}-node', 'containers': [
            {'name': product, 'image': 'fixture:v1',
             'ports': [{'name': port_name, 'containerPort': port, 'protocol': 'TCP'}]}]},
        'status': {'phase': 'Running', 'podIP': address,
                   'containerStatuses': [{'name': product, 'ready': True,
                                          'containerID': f'containerd://{name}',
                                          'state': {'running': {'startedAt': '2026-01-01T00:00:00Z'}}}]},
    }


class Kubernetes(BaseHTTPRequestHandler):
    pods = []
    closing = threading.Event()

    def do_GET(self):
        parsed = urlsplit(self.path)
        parts = parsed.path.strip('/').split('/')
        namespace = parts[3] if len(parts) == 5 and parts[2] == 'namespaces' else None
        items = [p for p in self.pods if namespace is None or p['metadata']['namespace'] == namespace]
        if parts[-1] != 'pods':
            items = []
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        if parse_qs(parsed.query).get('watch') == ['true']:
            events = [{'type': 'ADDED', 'object': p} for p in items]
            events.append({'type': 'BOOKMARK', 'object': {
                'apiVersion': 'v1', 'kind': 'Pod', 'metadata': {
                    'resourceVersion': '1', 'annotations': {'k8s.io/initial-events-end': 'true'}}}})
            try:
                for event in events:
                    self.wfile.write(json.dumps(event).encode() + b'\n')
                self.wfile.flush()
                self.closing.wait(20)
            except (BrokenPipeError, ConnectionResetError):
                pass
        else:
            self.wfile.write(json.dumps({'apiVersion': 'v1', 'kind': 'PodList',
                                        'metadata': {'resourceVersion': '1'}, 'items': items}).encode())

    def log_message(self, *_args):
        pass


class Target(BaseHTTPRequestHandler):
    requests = []

    def do_GET(self):
        self.requests.append((self.server.server_address[0], self.path, self.headers.get('Authorization')))
        body = b'{"items": [], "models": []}'
        if self.path == '/metrics':
            body = b'''# TYPE ollama_api_up gauge
ollama_api_up 1
# TYPE ollama_model_vram_bytes gauge
ollama_model_vram_bytes{model="fixture"} 4096
'''
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; version=0.0.4' if self.path == '/metrics' else 'application/json')
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_args):
        pass


class CollectionTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='workload-collection-')
        cls.addClassCleanup(cls.temp.cleanup)
        cls.directory = Path(cls.temp.name)
        cls.env = dict(os.environ, API_KEY='test', ELASTICSEARCH_PASSWORD='fixture',
                       K8S_CLUSTER_NAME='fixture-cluster', OLLAMA_NAMESPACE='team-a',
                       MCPO_NAMESPACE='team-b', MLFLOW_NAMESPACE='team-b',
                       MODEL_REGISTRY_NAMESPACE='team-b', OPENSEARCH_NAMESPACE='team-b',
                       NO_PROXY='*', no_proxy='*')
        for overlay in ('workload-probes.yaml', 'ollama-runtime.yaml'):
            result = subprocess.run([OPTIONS.collector, 'validate', '--config', str(ROOT / 'collector-config.yaml'),
                                     '--config', str(ROOT / 'examples' / overlay)], env=cls.env,
                                    capture_output=True, text=True, timeout=30)
            if result.returncode:
                raise AssertionError(result.stdout + result.stderr)

        def server(handler, host='127.0.0.1', port=0):
            instance = ThreadingHTTPServer((host, port), handler)
            threading.Thread(target=instance.serve_forever, daemon=True).start()
            cls.addClassCleanup(instance.server_close)
            cls.addClassCleanup(instance.shutdown)
            return instance

        # Separate loopback IPs represent independently discoverable pod endpoints.
        target = server(Target)
        cls.port = target.server_port
        server(Target, '127.0.0.2', cls.port)
        Kubernetes.pods = [
            pod('ollama-a', 'team-a', 'ollama', '127.0.0.1', cls.port),
            pod('ollama-b', 'team-a', 'ollama', '127.0.0.2', cls.port),
            pod('ollama-other-namespace', 'team-b', 'ollama', '127.0.0.1', cls.port),
            pod('mcpo', 'team-b', 'open-webui-mcpo', '127.0.0.1', cls.port),
            pod('mlflow', 'team-b', 'mlflow', '127.0.0.1', cls.port),
            pod('registry', 'team-b', 'model-registry', '127.0.0.1', cls.port,
                component='model-registry-server'),
            pod('registry-ui', 'team-b', 'model-registry', '127.0.0.1', cls.port,
                component='model-registry-ui'),
            pod('opensearch', 'team-b', 'opensearch', '127.0.0.1', cls.port),
            pod('ordinary-web', 'team-a', 'nginx', '127.0.0.1', cls.port),
        ]
        # Add the sidecar port to each Ollama fixture; the real scrape keeps its port name.
        for item in Kubernetes.pods:
            if item['metadata']['labels']['app.kubernetes.io/name'] == 'ollama':
                item['spec']['containers'][0]['ports'].append({
                    'name': 'ollama-metrics', 'containerPort': cls.port, 'protocol': 'TCP'})
        kube = server(Kubernetes)
        kubeconfig = cls.directory / 'kubeconfig.yaml'
        kubeconfig.write_text(yaml.safe_dump({
            'apiVersion': 'v1', 'kind': 'Config', 'current-context': 'fixture',
            'contexts': [{'name': 'fixture', 'context': {'cluster': 'fixture', 'user': 'fixture'}}],
            'clusters': [{'name': 'fixture', 'cluster': {'server': f'http://127.0.0.1:{kube.server_port}'}}],
            'users': [{'name': 'fixture', 'user': {}}],
        }))
        cls.env['KUBECONFIG'] = str(kubeconfig)
        token = cls.directory / 'token'
        token.write_text('fixture-token')
        original = yaml.safe_load((ROOT / 'collector-config.yaml').read_text())
        config = yaml.safe_load((ROOT / 'examples/workload-probes.yaml').read_text())
        runtime = yaml.safe_load((ROOT / 'examples/ollama-runtime.yaml').read_text())
        config['receivers'].update(runtime['receivers'])
        config['processors'] = {k: copy.deepcopy(original['processors'][k]) for k in (
            'memory_limiter', 'k8s_attributes', 'transform/suse_ai_resource', 'batch')}
        config['processors'].update(runtime['processors'])
        config['processors']['batch']['timeout'] = '100ms'
        k8s = config['processors']['k8s_attributes']
        k8s['auth_type'] = 'kubeConfig'
        k8s['extract'] = {'metadata': ['k8s.pod.name', 'k8s.pod.uid', 'k8s.namespace.name', 'k8s.node.name']}
        config['extensions'].pop('basicauth/ai_opensearch')
        config['extensions']['bearertokenauth/ai_model_registry']['filename'] = str(token)
        config['extensions']['k8s_observer/ai_workload_probes']['auth_type'] = 'kubeConfig'
        creator = config['receivers']['receiver_creator/ai_workload_probes']
        for receiver in creator['receivers'].values():
            # Preserve selector logic; replace only fixed production ports with the fixture port.
            receiver['rule'] = receiver['rule'].rsplit('port == ', 1)[0] + f'port == {cls.port}'
            receiver['config']['collection_interval'] = '1s'
        opensearch = creator['receivers']['http_check/opensearch']['config']['targets'][0]
        opensearch['endpoint'] = 'http://`endpoint`/'
        opensearch.pop('tls')
        opensearch.pop('auth')
        scrape = config['receivers']['prometheus/ollama_runtime']['config']['scrape_configs'][0]
        scrape['kubernetes_sd_configs'][0]['kubeconfig_file'] = str(kubeconfig)
        scrape['scrape_interval'], scrape['scrape_timeout'] = '1s', '1s'
        cls.output = cls.directory / 'metrics.jsonl'
        config['exporters'] = {'file': {'path': str(cls.output), 'format': 'json', 'flush_interval': '100ms'}}
        config['service']['extensions'] = list(config['extensions'])
        config['service']['pipelines'].update(runtime['service']['pipelines'])
        for pipeline in config['service']['pipelines'].values():
            pipeline['exporters'] = ['file']
        config['service']['telemetry'] = {'metrics': {'level': 'none'}}
        path = cls.directory / 'config.yaml'
        path.write_text(yaml.safe_dump(config, sort_keys=False))
        cls.log_path = cls.directory / 'collector.log'
        log = cls.log_path.open('w')
        cls.addClassCleanup(log.close)
        cls.process = subprocess.Popen([OPTIONS.collector, '--config', str(path)], env=cls.env,
                                       stdout=log, stderr=log)
        cls.addClassCleanup(cls.stop)
        deadline = time.monotonic() + 25
        while time.monotonic() < deadline:
            cls.metrics = cls.read_metrics()
            probes = {a.get('service.instance.id') for a, m in cls.metrics if m['name'] == 'httpcheck.status'}
            runtime_ids = {a.get('service.instance.id') for a, m in cls.metrics if m['name'] == 'ollama_api_up'}
            if len(probes) >= 6 and len(runtime_ids) >= 2:
                break
            if cls.process.poll() is not None:
                raise AssertionError(cls.log_path.read_text())
            time.sleep(0.2)
        else:
            raise AssertionError(f'Missing telemetry: {probes=} {runtime_ids=}\n' + cls.log_path.read_text())

    @classmethod
    def stop(cls):
        Kubernetes.closing.set()
        cls.process.terminate()
        try:
            cls.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait()
            raise AssertionError('Collector did not stop')

    @classmethod
    def read_metrics(cls):
        result = []
        if cls.output.exists():
            for line in cls.output.read_text().splitlines():
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue
                for resource in data.get('resourceMetrics', []):
                    attrs = unpack(resource['resource'].get('attributes', []))
                    for scope in resource.get('scopeMetrics', []):
                        result.extend((attrs, metric) for metric in scope.get('metrics', []))
        return result

    def test_probes_use_real_pod_identity_and_keep_replicas_separate(self):
        resources = {a['service.instance.id']: a for a, m in self.metrics if m['name'] == 'httpcheck.status'}
        expected = {'team-a-ollama-a-uid', 'team-a-ollama-b-uid', 'team-b-mcpo-uid',
                    'team-b-mlflow-uid', 'team-b-registry-uid', 'team-b-opensearch-uid'}
        self.assertEqual(set(resources), expected)
        for identity, attrs in resources.items():
            self.assertEqual(attrs['k8s.pod.uid'], identity)
            self.assertEqual(attrs['service.namespace'], attrs['k8s.namespace.name'])
            self.assertEqual(attrs['k8s.node.name'], attrs['service.namespace'] + '-node')
            self.assertEqual(attrs['k8s.cluster.name'], 'fixture-cluster')
            self.assertEqual(attrs['suse.ai.observation.kind'], 'http-probe')
        self.assertEqual(resources['team-b-opensearch-uid']['service.name'], 'opensearch')
        self.assertEqual(resources['team-b-mcpo-uid']['suse.ai.component.type'], 'mcp-server')

    def test_actual_probe_paths_and_registry_authentication(self):
        paths = {path for _, path, _ in Target.requests}
        self.assertTrue({'/api/tags', '/openapi.json', '/health', '/',
                         '/api/model_registry/v1alpha3/registered_models'} <= paths)
        for _, path, auth in Target.requests:
            if path == '/api/model_registry/v1alpha3/registered_models':
                self.assertEqual(auth, 'Bearer fixture-token')
        validation = [m for _, m in self.metrics if m['name'] == 'httpcheck.validation.passed']
        self.assertTrue(validation)

    def test_runtime_scrapes_are_scoped_to_ollama_processes(self):
        resources = {a['service.instance.id']: a for a, m in self.metrics if m['name'] == 'ollama_api_up'}
        self.assertEqual(set(resources), {'team-a-ollama-a-uid', 'team-a-ollama-b-uid'})
        for identity, attrs in resources.items():
            self.assertEqual(attrs['service.name'], 'ollama')
            self.assertEqual(attrs['service.namespace'], 'team-a')
            self.assertEqual(attrs['k8s.pod.uid'], identity)
            self.assertEqual(attrs['k8s.node.name'], 'team-a-node')
            self.assertEqual(attrs['k8s.cluster.name'], 'fixture-cluster')
            self.assertEqual(attrs['suse.ai.product'], 'ollama')
            self.assertNotIn('suse.ai.observation.kind', attrs)
        allocations = [m for _, m in self.metrics if m['name'] == 'ollama_model_vram_bytes']
        self.assertTrue(allocations)
        for metric in allocations:
            point = metric['gauge']['dataPoints'][0]
            self.assertEqual(float(point.get('asDouble', point.get('asInt'))), 4096)
            self.assertEqual(unpack(point['attributes'])['model'], 'fixture')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--collector', required=True)
    OPTIONS, remaining = parser.parse_known_args()
    unittest.main(argv=[__file__, *remaining])
