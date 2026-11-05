"""Exercise database discovery, resource scope and exact CLIENT joins with the Collector."""

import argparse
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
import urllib.request

import yaml

from test_collector import attributes, free_port, unpack
from test_workload_collection import pod

ROOT = Path(__file__).resolve().parents[1]
OPTIONS = None
PRODUCTS = ('milvus', 'qdrant', 'opensearch')
PREFIXES = ('MILVUS', 'QDRANT', 'ELASTICSEARCH')
PEERS = ('suse.ai.peer.service.name', 'suse.ai.peer.service.namespace', 'suse.ai.peer.cluster')


class Kubernetes(BaseHTTPRequestHandler):
    objects = {}
    closing = threading.Event()

    def do_GET(self):
        parsed = urlsplit(self.path)
        parts = parsed.path.strip('/').split('/')
        kind, items = self.objects.get(parts[-1], ('Pod', []))
        if len(parts) == 5 and parts[2] == 'namespaces':
            items = [p for p in items if p['metadata']['namespace'] == parts[3]]
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        try:
            if parse_qs(parsed.query).get('watch') == ['true']:
                for item in items:
                    self.wfile.write(json.dumps({'type': 'ADDED', 'object': item}).encode() + b'\n')
                self.wfile.write(json.dumps({'type': 'BOOKMARK', 'object': {
                    'apiVersion': 'v1', 'kind': kind, 'metadata': {'resourceVersion': '1',
                    'annotations': {'k8s.io/initial-events-end': 'true'}}}}).encode() + b'\n')
                self.wfile.flush()
                self.closing.wait(30)
            else:
                self.wfile.write(json.dumps({'apiVersion': 'v1', 'kind': kind + 'List',
                                            'metadata': {'resourceVersion': '1'}, 'items': items}).encode())
        except (BrokenPipeError, ConnectionResetError):
            pass

    def log_message(self, *_args):
        pass


class Metrics(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; version=0.0.4')
        self.end_headers()
        self.wfile.write(b'# TYPE database_fixture gauge\ndatabase_fixture 7\n')

    def log_message(self, *_args):
        pass


class DatabaseProfiles(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='database-profiles-')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        if OPTIONS.evidence_dir:
            self.directory = Path(OPTIONS.evidence_dir) / self.id().rsplit('.', 1)[-1]
            self.directory.mkdir(parents=True, exist_ok=True)
        self.env = {k: v for k, v in os.environ.items() if not k.startswith(
            PREFIXES + ('K8S_CLUSTER_', 'SUSE_AI_', 'OTEL_RESOURCE_'))}
        self.env.update(API_KEY='test', ELASTICSEARCH_PASSWORD='test', K8S_CLUSTER_NAME='fixture-cluster',
                        SUSE_AI_NAMESPACE='data', OTEL_RESOURCE_ATTRIBUTES='', NO_PROXY='*', no_proxy='*')
        self.config = yaml.safe_load((ROOT / 'collector-config.yaml').read_text())
        self.profiles = {p: yaml.safe_load((ROOT / (p + '.yaml')).read_text()) for p in PRODUCTS}
        for overlay in self.profiles.values():
            for section in ('receivers', 'processors'):
                self.config[section].update(overlay.get(section, {}))
            self.config['service']['pipelines'].update(overlay['service']['pipelines'])
        self.config['processors']['k8s_attributes'] = {'passthrough': True}
        self.config['processors']['batch']['timeout'] = '100ms'
        self.config['service']['telemetry'] = {'metrics': {'level': 'none'}}
        self.config['connectors']['service_graph/suse_ai']['metrics_flush_interval'] = '100ms'
        self.config['exporters'] = {'file/test': {'path': str(self.directory / 'output.jsonl'),
                                              'flush_interval': '100ms'}}

    def server(self, handler, host='127.0.0.1', port=0):
        server = ThreadingHTTPServer((host, port), handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def discovery(self):
        first = self.server(Metrics)
        self.server(Metrics, '127.0.0.2', first.server_port)
        self.target = f'127.0.0.1:{first.server_port}'
        services, endpoints, pods = [], [], []
        for product in ('milvus', 'qdrant'):
            self.env[product.upper() + '_METRICS_PORT'] = str(first.server_port)
            for name, namespace in ((product, 'data'), (product + '-other', 'data'), (product, 'other')):
                metadata = {'name': name, 'namespace': namespace, 'resourceVersion': '1'}
                services.append({'apiVersion': 'v1', 'kind': 'Service', 'metadata': metadata,
                                 'spec': {'ports': [{'name': 'metrics', 'port': first.server_port}]}})
                addresses = []
                for index in range(2):
                    item = pod(f'{name}-{index}', namespace, product, f'127.0.0.{index+1}', first.server_port)
                    pods.append(item)
                    addresses.append({'ip': item['status']['podIP'], 'targetRef': {
                        'kind': 'Pod', 'name': item['metadata']['name'], 'namespace': namespace,
                        'uid': item['metadata']['uid']}})
                unready = pod(name + '-unready', namespace, product, '127.0.0.3', first.server_port)
                pods.append(unready)
                endpoints.append({'apiVersion': 'v1', 'kind': 'Endpoints', 'metadata': metadata,
                    'subsets': [{'addresses': addresses + [{'ip': '127.0.0.4'}],
                        'notReadyAddresses': [{'ip': '127.0.0.3', 'targetRef': {'kind': 'Pod',
                            'name': unready['metadata']['name'], 'namespace': namespace,
                            'uid': unready['metadata']['uid']}}],
                        'ports': [{'name': 'metrics', 'port': first.server_port, 'protocol': 'TCP'},
                                  {'name': 'wrong-port', 'port': free_port(), 'protocol': 'TCP'}]}]})
        Kubernetes.objects = {'services': ('Service', services), 'endpoints': ('Endpoints', endpoints),
                              'pods': ('Pod', pods)}
        Kubernetes.closing.clear()
        self.addCleanup(Kubernetes.closing.set)
        api = self.server(Kubernetes)
        kubeconfig = self.directory / 'kubeconfig.yaml'
        kubeconfig.write_text(yaml.safe_dump({
            'apiVersion': 'v1', 'kind': 'Config', 'current-context': 'test',
            'contexts': [{'name': 'test', 'context': {'cluster': 'test', 'user': 'test'}}],
            'clusters': [{'name': 'test', 'cluster': {'server': f'http://127.0.0.1:{api.server_port}'}}],
            'users': [{'name': 'test', 'user': {}}]}))
        for product in ('milvus', 'qdrant'):
            for job in self.config['receivers']['prometheus/' + product]['config']['scrape_configs']:
                job['scrape_interval'], job['scrape_timeout'] = '1s', '1s'
                if 'kubernetes_sd_configs' in job:
                    job['kubernetes_sd_configs'][0]['kubeconfig_file'] = str(kubeconfig)

    def start(self, pipelines):
        self.config['service']['pipelines'] = {p: self.config['service']['pipelines'][p] for p in pipelines}
        for name, pipeline in self.config['service']['pipelines'].items():
            pipeline['exporters'] = ['file/test', 'count/suse_ai_clients', 'service_graph/suse_ai'] if name == 'traces' else ['file/test']
            if name == 'traces':
                pipeline['receivers'] = ['otlp']
        used = {r for p in self.config['service']['pipelines'].values() for r in p['receivers']}
        self.config['receivers'] = {k: v for k, v in self.config['receivers'].items() if k in used}
        self.ports = {}
        for name in self.config['receivers']:
            if name.startswith('otlp'):
                port = free_port()
                self.ports[name] = port
                self.config['receivers'][name] = {'protocols': {'http': {'endpoint': f'127.0.0.1:{port}'}}}
        self.health = f'127.0.0.1:{free_port()}'
        self.config['extensions'] = {'health_check': {'endpoint': self.health}}
        self.config['service']['extensions'] = ['health_check']
        path = self.directory / 'config.yaml'
        path.write_text(yaml.safe_dump(self.config, sort_keys=False))
        self.log_path = self.directory / 'collector.log'
        log = self.log_path.open('w')
        self.addCleanup(log.close)
        self.process = subprocess.Popen([OPTIONS.collector, '--config=' + str(path)], env=self.env,
                                        stdout=log, stderr=log)
        self.addCleanup(self.stop)
        def healthy():
            try:
                return urllib.request.urlopen('http://' + self.health, timeout=0.2).status == 200
            except OSError:
                return False
        self.wait(healthy)

    def stop(self):
        self.process.terminate()
        try:
            self.process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            self.process.kill()
            self.process.wait()
            self.fail('Collector shutdown timed out')

    def wait(self, predicate):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            self.assertIsNone(self.process.poll(), self.log_path.read_text())
            value = predicate()
            if value:
                return value
            time.sleep(0.1)
        self.fail('Missing telemetry: ' + self.log_path.read_text()[-6000:])

    def output(self, key):
        rows = []
        path = self.directory / 'output.jsonl'
        for line in path.read_text().splitlines() if path.exists() else []:
            try:
                rows.extend(json.loads(line).get(key, []))
            except json.JSONDecodeError:
                pass
        return rows

    def metrics(self, name='database_fixture'):
        return [(unpack(r['resource']['attributes']), m)
                for r in self.output('resourceMetrics') for s in r['scopeMetrics']
                for m in s['metrics'] if m['name'] == name]

    def send(self, signal, payload, receiver='otlp'):
        request = urllib.request.Request(f'http://127.0.0.1:{self.ports[receiver]}/v1/{signal}',
            json.dumps(payload).encode(), {'Content-Type': 'application/json'})
        with urllib.request.urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 200)

    def test_discovery_keeps_two_real_pods_per_service(self):
        self.discovery()
        self.start(['metrics/milvus', 'metrics/qdrant'])
        rows = self.wait(lambda: self.metrics() if len({a['service.instance.id'] for a, _ in self.metrics()}) == 4 else None)
        for product in ('milvus', 'qdrant'):
            resources = {a['service.instance.id']: a for a, _ in rows if a['service.name'] == product}
            self.assertEqual(set(resources), {f'data-{product}-{i}-uid' for i in range(2)})
            for uid, attrs in resources.items():
                self.assertEqual(attrs['k8s.pod.uid'], uid)
                self.assertEqual(attrs['k8s.pod.name'], uid[len('data-'):-len('-uid')])
                self.assertEqual(attrs['k8s.node.name'], 'data-node')
                self.assertEqual(attrs['k8s.namespace.name'], 'data')
                self.assertEqual(attrs['k8s.cluster.name'], 'fixture-cluster')
                self.assertEqual(attrs['service.namespace'], 'data')
                self.assertEqual(attrs['db.system'], product)
                self.assertEqual(attrs['db.system.name'], product)
                self.assertEqual(attrs['suse.ai.product'], product)
        self.assertEqual(len({a['service.instance.id'] for a, _ in self.metrics('up')}), 4)

    def static(self, local):
        self.discovery()
        for p in ('MILVUS', 'QDRANT'):
            self.env[p + '_METRICS_ENDPOINT'] = self.target
            if local:
                self.env[p + '_TARGET_IN_CLUSTER'] = 'true'
        self.start(['metrics/milvus', 'metrics/qdrant'])
        self.wait(lambda: len({a['service.name'] for a, _ in self.metrics()}) == 2)
        time.sleep(2)  # Ensure discovery has time to produce an unwanted duplicate.
        for attrs, metric in self.metrics('up'):
            self.assertNotIn('k8s.pod.uid', attrs)
            self.assertNotIn('k8s.node.name', attrs)
            self.assertEqual(attrs['service.instance.id'], self.target)
            self.assertEqual(attrs.get('k8s.cluster.name'), 'fixture-cluster' if local else None)
            self.assertEqual(attrs.get('k8s.namespace.name'), 'data' if local else None)
            self.assertEqual(float(metric['gauge']['dataPoints'][0].get('asDouble', 0)), 1)

    def test_external_override_selects_only_static_without_cluster(self):
        self.static(False)

    def test_verified_local_static_has_cluster_without_pod(self):
        self.static(True)

    def scope(self, external):
        pipelines = []
        for p, product, port in zip(PREFIXES, PRODUCTS, (9091, 6333, 9200)):
            name = 'elasticsearch' if product == 'opensearch' else product
            host = 'opensearch-cluster-master-headless' if product == 'opensearch' else product
            endpoint = f'{host}.data.svc.cluster.local:{port}'
            self.env[p + ('_ENDPOINT' if product == 'opensearch' else '_METRICS_ENDPOINT')] = (
                'http://' if product == 'opensearch' else '') + ('remote.example:9999' if external else endpoint)
            receiver = 'otlp/' + name
            self.config['receivers'][receiver] = {}
            pipeline = 'metrics/' + name
            self.config['service']['pipelines'][pipeline]['receivers'] = [receiver]
            pipelines.append(pipeline)
        self.start(pipelines)
        for pipeline in pipelines:
            self.send('metrics', {'resourceMetrics': [{'resource': {}, 'scopeMetrics': [{'metrics': [
                {'name': 'scope_fixture', 'gauge': {'dataPoints': [{'asInt': '1', 'timeUnixNano': str(time.time_ns())}]}}]}]}]},
                'otlp/' + pipeline.split('/')[1])
        rows = self.wait(lambda: self.metrics('scope_fixture') if len(self.metrics('scope_fixture')) == 3 else None)
        for attrs, _ in rows:
            self.assertEqual(attrs.get('k8s.cluster.name'), None if external else 'fixture-cluster')
            self.assertNotIn('k8s.pod.uid', attrs)
            self.assertNotIn('k8s.node.name', attrs)
            self.assertNotIn('service.instance.id', attrs)

    def test_canonical_static_and_aggregate_cluster_without_pod(self):
        self.scope(False)

    def test_external_aggregate_does_not_inherit_collectors_cluster(self):
        self.scope(True)

    def association(self, enabled, *, external=False, profiles=True, custom=False):
        if enabled:
            self.env.update({p + '_ASSOCIATE_CLIENT_SPANS': 'true' for p in PREFIXES})
        if not profiles:
            base = yaml.safe_load((ROOT / 'collector-config.yaml').read_text())
            for name in ('milvus', 'qdrant', 'opensearch'):
                self.config['processors']['transform/' + name + '_peer'] = base['processors']['transform/' + name + '_peer']
        if external:
            self.env.update(MILVUS_METRICS_ENDPOINT='remote.example:9091', QDRANT_METRICS_ENDPOINT='remote.example:6333',
                            ELASTICSEARCH_ENDPOINT='https://remote.example:9200')
        if custom:
            self.env['K8S_CLUSTER_DOMAIN'] = 'cluster.example'
            self.env['ELASTICSEARCH_SYSTEM'] = 'elasticsearch'
            for p in PREFIXES:
                self.env.update({p + '_K8S_SERVICE_NAME': 'custom-' + p.lower(), p + '_NAMESPACE': 'tenant',
                                 p + '_SERVICE_NAME': 'native-' + p.lower(), p + '_CLIENT_PORT': '12345'})
        self.start(['traces', 'metrics/suse_ai_observations'])
        resources, expected = [], {}
        for prefix, product, port in zip(PREFIXES, PRODUCTS, (19530, 6333, 9200)):
            service = ('opensearch-cluster-master-headless' if product == 'opensearch' else product)
            host = f'{service}.data.svc.cluster.local'
            system, namespace, native = product, 'data', product
            if custom:
                host, port = f'custom-{prefix.lower()}.tenant.svc.cluster.example', 12345
                system = 'elasticsearch' if product == 'opensearch' else product
                namespace, native = 'tenant', 'native-' + prefix.lower()
            base = {'db.system.name': system, 'server.address': host, 'server.port': str(port)}
            cases = [
                ('exact', {}, {}, 3, True), ('integer-port', {'server.port': port}, {}, 3, True),
                ('short', {'server.address': service}, {}, 3, False),
                ('partial-dns', {'server.address': service + '.' + namespace}, {}, 3, False),
                ('cross-domain', {'server.address': host + '.remote'}, {}, 3, False),
                ('wrong-port', {'server.port': str(port+1)}, {}, 3, False),
                ('no-port', {'server.port': None}, {}, 3, False),
                ('other-db', {'db.system.name': 'other'}, {}, 3, False),
                ('other-cluster', {}, {'k8s.cluster.name': 'remote'}, 3, False),
                ('unknown-cluster', {}, {'k8s.cluster.name': None}, 3, False),
                ('unknown-cluster-with-pod', {}, {'k8s.cluster.name': None, 'k8s.pod.uid': 'remote-pod'}, 3, False),
                ('unknown-cluster-with-node', {}, {'k8s.cluster.name': None, 'k8s.node.name': 'remote-node'}, 3, False),
                ('empty-cluster', {}, {'k8s.cluster.name': ''}, 3, False),
                ('server', {}, {}, 2, False), ('internal', {}, {}, 1, False),
                ('legacy', {'db.system.name': None, 'db.system': system, 'server.address': None,
                            'net.peer.name': host, 'server.port': None, 'net.peer.port': str(port)}, {}, 3, True),
            ]
            cases += [('existing-' + str(i), {key: 'existing'}, {}, 3, False) for i, key in enumerate(PEERS)]
            cases += [('empty-peers', {key: '' for key in PEERS}, {}, 3, True)]
            for case, override, resource_override, kind, match in cases:
                name = product + '-' + case
                values = {k: v for k, v in {**base, **override}.items() if v is not None}
                span_attrs = attributes({k: v for k, v in values.items() if not isinstance(v, int)})
                if isinstance(values.get('server.port'), int):
                    span_attrs.append({'key': 'server.port', 'value': {'intValue': str(values['server.port'])}})
                resource = {k: v for k, v in {'service.name': 'caller', 'service.namespace': 'apps',
                    'k8s.cluster.name': 'fixture-cluster', **resource_override}.items() if v is not None}
                index, now = len(resources) + 1, time.time_ns()
                resources.append({'resource': {'attributes': attributes(resource)}, 'scopeSpans': [{'spans': [{
                    'name': name, 'traceId': f'{index:032x}', 'spanId': f'{index:016x}', 'kind': kind,
                    'startTimeUnixNano': str(now), 'endTimeUnixNano': str(now+1000000), 'attributes': span_attrs}]}]})
                expected[name] = dict(zip(PEERS, (native, namespace, 'fixture-cluster'))) if (
                    match and enabled and profiles and not external) else {k: v for k, v in values.items() if k in PEERS}
        self.send('traces', {'resourceSpans': resources})
        def spans():
            return {s['name']: unpack(s.get('attributes', [])) for r in self.output('resourceSpans')
                    for scope in r['scopeSpans'] for s in scope['spans']}
        self.wait(lambda: len(spans()) == len(expected))
        self.assertEqual({n: {k: v for k, v in a.items() if k in PEERS} for n, a in spans().items()}, expected)
        for resource in self.output('resourceSpans'):
            attrs = unpack(resource['resource']['attributes'])
            self.assertEqual(attrs['service.name'], 'caller')
            self.assertEqual(attrs['service.namespace'], 'apps')
            self.assertNotIn('db.system.name', attrs)
            if 'k8s.pod.uid' in attrs:
                self.assertEqual(attrs['k8s.pod.uid'], 'remote-pod')
        if enabled and profiles and not external:
            calls = self.wait(lambda: self.metrics('suse.ai.service.calls'))
            destinations = {unpack(p['attributes'])['server'] for _, m in calls for p in m['gauge']['dataPoints']}
            self.assertEqual(destinations, {self.env.get(p + '_SERVICE_NAME', product) for p, product in zip(PREFIXES, PRODUCTS)})
        errors = [line for line in self.log_path.read_text().splitlines() if 'failed to execute' in line.lower()]
        self.assertEqual(errors, [])

    def test_association_is_opt_in(self):
        self.association(False)

    def test_association_requires_loaded_profile(self):
        self.association(True, profiles=False)

    def test_exact_same_cluster_clients_and_legacy_normalization(self):
        self.association(True)

    def test_external_profile_cannot_resolve_local_service(self):
        self.association(True, external=True)

    def test_association_identity_and_port_are_environment_configurable(self):
        self.association(True, custom=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--collector', required=True)
    parser.add_argument('--evidence-dir')
    OPTIONS, remaining = parser.parse_known_args()
    unittest.main(argv=[__file__, *remaining])
