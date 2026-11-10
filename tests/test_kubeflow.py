"""Exercise the bundled Kubeflow jobs with real pod discovery and HTTPS scrapes."""

import argparse
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import random
import ssl
import subprocess
import tempfile
import threading
import time
import unittest

import yaml

from test_collector import unpack
from test_database_profiles import Kubernetes
from test_workload_collection import pod

ROOT = Path(__file__).resolve().parents[1]
OPTIONS = None
TOKEN = 'kubeflow-fixture-not-a-secret'


class Metrics(BaseHTTPRequestHandler):
    protected = False

    def do_GET(self):
        if self.path != '/metrics':
            self.send_error(404)
            return
        if self.protected and self.headers.get('Authorization') != 'Bearer ' + TOKEN:
            self.send_error(403)
            return
        self.send_response(200)
        self.send_header('Content-Type', 'text/plain; version=0.0.4')
        self.end_headers()
        self.wfile.write(b'# TYPE kubeflow_fixture_duration_seconds histogram\n'
                         b'kubeflow_fixture_duration_seconds_bucket{le="0.5"} 1\n'
                         b'kubeflow_fixture_duration_seconds_bucket{le="+Inf"} 2\n'
                         b'kubeflow_fixture_duration_seconds_sum 1.5\n'
                         b'kubeflow_fixture_duration_seconds_count 2\n')

    def log_message(self, *_args):
        pass


class KubeflowIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='kubeflow-profile-')
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        if OPTIONS.evidence_dir:
            self.directory = Path(OPTIONS.evidence_dir) / self.id().rsplit('.', 1)[-1]
            self.directory.mkdir(parents=True, exist_ok=True)
        self.token = self.directory / 'token'
        self.token.write_text(TOKEN + '\n')
        self.env = {k: v for k, v in os.environ.items()
                    if not k.startswith(('KUBEFLOW_', 'KSERVE_', 'OTEL_RESOURCE_'))}
        self.env.update(API_KEY='test', K8S_CLUSTER_NAME='fixture-cluster',
                        KUBEFLOW_METRICS_TOKEN_FILE=str(self.token),
                        OTEL_RESOURCE_ATTRIBUTES='', NO_PROXY='*', no_proxy='*')

    def server(self, handler, address='127.0.0.1', port=0, tls=None):
        server = ThreadingHTTPServer((address, port), handler)
        if tls:
            server.socket = tls.wrap_socket(server.socket, server_side=True)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return server

    def run_scrapes(self, *, custom=False, wrong_token=False, empty=False):
        namespace = 'ml-platform' if custom else 'kubeflow'
        model_namespace = 'team-models' if custom else 'kubeflow-user-example-com'
        if custom:
            self.env.update(KUBEFLOW_NAMESPACE=namespace, KSERVE_NAMESPACE=model_namespace)
        subnet = random.randint(20, 240)
        addresses = [f'127.0.{subnet}.1', f'127.0.{subnet}.2']
        cert, key = self.directory / 'cert.pem', self.directory / 'key.pem'
        subprocess.run(['openssl', 'req', '-x509', '-newkey', 'rsa:2048', '-nodes',
                        '-keyout', str(key), '-out', str(cert), '-days', '1',
                        '-subj', '/CN=kubeflow-fixture', '-addext',
                        'subjectAltName=IP:' + ',IP:'.join(addresses)],
                       check=True, capture_output=True)
        tls = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cert, key)
        if custom:
            self.env.update(KUBEFLOW_METRICS_INSECURE_SKIP_VERIFY='false',
                            KUBEFLOW_METRICS_CA_FILE=str(cert))
        if wrong_token:
            self.token.write_text('wrong-fixture-token\n')
        protected = type('ProtectedMetrics', (Metrics,), {'protected': True})
        expected = {}
        pods = []
        cases = [
            ('pipelines', namespace, {'app': 'ml-pipeline'}, 8888,
             'kubeflow-pipelines', 'kubeflow-pipelines', False, addresses[0]),
            ('workflow', namespace, {'app': 'workflow-controller'}, 9090,
             'kubeflow-workflow-controller', 'kubeflow-pipelines', True, addresses[0]),
            ('controller', namespace, {'control-plane': 'kserve-controller-manager'}, 8443,
             'kserve-controller', 'kserve', True, addresses[0]),
            ('iris-1', model_namespace, {'serving.kserve.io/inferenceservice': 'iris'}, 8080,
             'iris', 'kserve', False, addresses[0]),
            ('iris-2', model_namespace, {'serving.kserve.io/inferenceservice': 'iris'}, 8080,
             'iris', 'kserve', False, addresses[1]),
        ]
        for name, ns, labels, port, service, product, secure, address in cases:
            self.server(protected if secure else Metrics, address, port, tls if secure else None)
            item = pod(name, ns, product, address, port)
            item['metadata']['labels'] = labels
            pods.append(item)
            expected[item['metadata']['uid']] = (ns, service, product, secure)
            # Every job must reject the wrong namespace, port, phase or label.
            for field in ('namespace', 'port', 'phase', 'label'):
                other = copy.deepcopy(item)
                other['metadata']['name'] += '-' + field
                other['metadata']['uid'] += '-' + field
                if field == 'namespace':
                    other['metadata']['namespace'] = 'unrelated'
                elif field == 'port':
                    other['spec']['containers'][0]['ports'][0]['containerPort'] = 7777
                elif field == 'phase':
                    other['status']['phase'] = 'Succeeded'
                else:
                    other['metadata']['labels'] = {'unrelated': 'true'}
                pods.append(other)
        Kubernetes.objects = {'pods': ('Pod', [] if empty else pods)}
        Kubernetes.closing.clear()
        api = self.server(Kubernetes)
        self.addCleanup(Kubernetes.closing.set)
        kubeconfig = self.directory / 'kubeconfig.yaml'
        kubeconfig.write_text(yaml.safe_dump({
            'apiVersion': 'v1', 'kind': 'Config', 'current-context': 'fixture',
            'contexts': [{'name': 'fixture', 'context': {'cluster': 'fixture', 'user': 'fixture'}}],
            'clusters': [{'name': 'fixture', 'cluster': {'server': f'http://127.0.0.1:{api.server_port}'}}],
            'users': [{'name': 'fixture', 'user': {}}]}))
        base = yaml.safe_load((ROOT / 'collector-config.yaml').read_text())
        config = yaml.safe_load((ROOT / 'kubeflow.yaml').read_text())
        config['processors'] = base['processors']
        config['processors']['batch']['timeout'] = '100ms'
        for job in config['receivers']['prometheus/kubeflow']['config']['scrape_configs']:
            job['kubernetes_sd_configs'][0]['kubeconfig_file'] = str(kubeconfig)
            job['scrape_interval'], job['scrape_timeout'] = '1s', '1s'
        output = self.directory / 'metrics.jsonl'
        output.unlink(missing_ok=True)
        config['exporters'] = {'file/test': {'path': str(output), 'flush_interval': '100ms'}}
        config['service']['pipelines']['metrics/kubeflow']['exporters'] = ['file/test']
        config['service']['telemetry'] = {'logs': {'encoding': 'json'}, 'metrics': {'level': 'none'}}
        path = self.directory / 'config.yaml'
        path.write_text(yaml.safe_dump(config, sort_keys=False))
        log_path = self.directory / 'collector.log'
        found, histograms = {}, {}
        with log_path.open('w') as log:
            process = subprocess.Popen([OPTIONS.collector, '--config=' + str(path)],
                                       env=self.env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + (6 if empty else 25)
                while time.monotonic() < deadline:
                    self.assertIsNone(process.poll(), log_path.read_text())
                    for line in output.read_text().splitlines() if output.exists() else []:
                        try:
                            data = json.loads(line)
                        except json.JSONDecodeError:
                            continue
                        for resource in data.get('resourceMetrics', []):
                            attrs = unpack(resource['resource']['attributes'])
                            uid = attrs.get('k8s.pod.uid')
                            for scope in resource['scopeMetrics']:
                                for metric in scope['metrics']:
                                    if metric['name'] == 'up':
                                        found[uid] = (attrs, metric['gauge']['dataPoints'][0])
                                    if metric['name'] == 'kubeflow_fixture_duration_seconds':
                                        histograms[uid] = metric['histogram']['dataPoints'][0]
                    successful = {uid for uid, (_, _, _, secure) in expected.items()
                                  if not (secure and wrong_token)}
                    if not empty and set(found) >= set(expected) and set(histograms) >= successful:
                        break
                    time.sleep(0.1)
            finally:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    self.fail('Collector shutdown timed out')
        self.assertEqual(process.returncode, 0, log_path.read_text())
        self.assertIn('Everything is ready. Begin running and processing data.', log_path.read_text())
        self.assertEqual(set(found), set() if empty else set(expected))
        for uid, (attrs, point) in found.items():
            ns, service, product, secure = expected[uid]
            self.assertEqual(float(point.get('asDouble', point.get('asInt'))),
                             0 if secure and wrong_token else 1)
            self.assertEqual(attrs['service.name'], service)
            self.assertEqual(attrs['service.namespace'], ns)
            self.assertEqual(attrs['k8s.namespace.name'], ns)
            self.assertEqual(attrs['k8s.cluster.name'], 'fixture-cluster')
            self.assertEqual(attrs['service.instance.id'], uid)
            self.assertEqual(attrs['suse.ai.product'], product)
            expected_pod = next(p for p in pods if p['metadata']['uid'] == uid)
            self.assertEqual(attrs['k8s.pod.name'], expected_pod['metadata']['name'])
            self.assertEqual(attrs['k8s.node.name'], expected_pod['spec']['nodeName'])
            labels = unpack(point['attributes'])
            self.assertEqual(labels['service_name'], service)
            self.assertEqual(labels['service_namespace'], ns)
        self.assertEqual(set(histograms), set() if empty else successful)
        for point in histograms.values():
            self.assertEqual(point['explicitBounds'], [0.5])
            self.assertEqual([int(v) for v in point['bucketCounts']], [1, 1])
            self.assertEqual(int(point['count']), 2)
        if not wrong_token:
            self.assertNotIn('"level":"error"', log_path.read_text())
            self.assertNotIn('Failed to scrape', log_path.read_text())

    def test_default_discovery_preserves_pod_identity_and_histograms(self):
        self.run_scrapes()

    def test_custom_namespaces_and_verified_controller_tls(self):
        self.run_scrapes(custom=True)

    def test_wrong_token_rejects_only_protected_controllers(self):
        self.run_scrapes(wrong_token=True)

    def test_empty_namespaces_have_no_scrape_targets(self):
        self.run_scrapes(empty=True)

    def test_missing_controller_token_fails_validation(self):
        self.token.unlink()
        result = subprocess.run([OPTIONS.collector, 'validate',
                                 '--config=' + str(ROOT / 'collector-config.yaml'),
                                 '--config=' + str(ROOT / 'kubeflow.yaml')],
                                env=self.env, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('authorization credentials file', result.stderr)
        self.assertIn('no such file', result.stderr)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--collector', required=True)
    parser.add_argument('--evidence-dir')
    OPTIONS, remaining = parser.parse_known_args()
    unittest.main(argv=[__file__] + remaining, verbosity=2)
