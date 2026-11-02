"""Validate profile composition with the Collector; exercise empty Kubernetes discovery."""

import argparse
import copy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import itertools
import json
import os
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time
import unittest
from urllib.parse import parse_qs, urlsplit
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[1]
OPTIONS = None
PROFILES = ('milvus.yaml', 'qdrant.yaml', 'opensearch.yaml',
            'examples/ollama-runtime.yaml', 'examples/workload-probes.yaml')
LITELLM_MODES = (None, 'litellm-receiver.yaml', 'litellm-receiver-no-auth.yaml')


def free_port():
    with socket.socket() as sock:
        sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class EmptyKubernetes(BaseHTTPRequestHandler):
    """Kubernetes list/watch API with no products, pods, Services or Endpoints."""
    requests = []
    closing = threading.Event()
    kinds = {'pods': 'Pod', 'services': 'Service', 'endpoints': 'Endpoints',
             'nodes': 'Node', 'namespaces': 'Namespace', 'replicasets': 'ReplicaSet',
             'deployments': 'Deployment', 'statefulsets': 'StatefulSet',
             'daemonsets': 'DaemonSet', 'jobs': 'Job', 'cronjobs': 'CronJob'}

    def do_GET(self):
        parsed = urlsplit(self.path)
        self.requests.append(parsed.path)
        kind = self.kinds.get(parsed.path.rsplit('/', 1)[-1])
        if kind is None:
            self.send_error(404)
            return
        api = 'apps/v1' if '/apis/apps/' in parsed.path else 'batch/v1' if '/apis/batch/' in parsed.path else 'v1'
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        try:
            if parse_qs(parsed.query).get('watch') == ['true']:
                self.wfile.write(json.dumps({'type': 'BOOKMARK', 'object': {
                    'apiVersion': api, 'kind': kind, 'metadata': {
                        'resourceVersion': '1', 'annotations': {'k8s.io/initial-events-end': 'true'}}}}).encode() + b'\n')
                self.wfile.flush()
                self.closing.wait(60)
            else:
                self.wfile.write(json.dumps({'apiVersion': api, 'kind': kind + 'List',
                                            'metadata': {'resourceVersion': '1'}, 'items': []}).encode())
        except (BrokenPipeError, ConnectionResetError):
            # Watch clients disconnect when the collector stops.
            pass

    def log_message(self, *_args):
        pass


class ProfileIntegration(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if OPTIONS.evidence_dir:
            cls.directory = Path(OPTIONS.evidence_dir)
            cls.directory.mkdir(parents=True, exist_ok=True)
        else:
            cls.temp = tempfile.TemporaryDirectory(prefix='collector-profiles-')
            cls.addClassCleanup(cls.temp.cleanup)
            cls.directory = Path(cls.temp.name)
        cls.env = dict(os.environ, API_KEY='test-key', ELASTICSEARCH_PASSWORD='test-password',
                       K8S_CLUSTER_NAME='test-cluster', SUSE_AI_NAMESPACE='ai-test',
                       GPU_NAMESPACE='gpu-test', OTEL_RESOURCE_ATTRIBUTES='',
                       LITELLM_METRICS_KEY_FILE=str(ROOT / 'tests/fixtures/litellm-metrics-key'))
        cls.base = yaml.safe_load((ROOT / 'collector-config.yaml').read_text())

    def command(self, action, profiles):
        args = [OPTIONS.collector, action, '--config=' + str(ROOT / 'collector-config.yaml')]
        return args + ['--config=' + str(ROOT / p) for p in profiles]

    def test_all_supported_combinations(self):
        count = 0
        with (self.directory / 'profile-validation.log').open('w') as output:
            for mode, flags in itertools.product(LITELLM_MODES, itertools.product((False, True), repeat=len(PROFILES))):
                profiles = [p for p, enabled in zip(PROFILES, flags) if enabled]
                if mode:
                    profiles.append(mode)
                expected_pipelines = set(self.base['service']['pipelines'])
                expected_extensions = set(self.base['service']['extensions'])
                expected_receivers = set(self.base['receivers'])
                for profile in profiles:
                    extra = yaml.safe_load((ROOT / profile).read_text())
                    expected_pipelines.update(extra['service']['pipelines'])
                    expected_extensions.update(extra.get('extensions', {}))
                    expected_receivers.update(extra['receivers'])
                # Base must be first. Optional profiles commute: check both orders.
                orders = [profiles]
                if len(profiles) > 1:
                    orders.append(list(reversed(profiles)))
                for ordered in orders:
                    with self.subTest(profiles=ordered):
                        result = subprocess.run(self.command('validate', ordered), env=self.env,
                                                capture_output=True, text=True, timeout=30)
                        output.write('validate ' + ','.join(ordered or ['base-only']) + f': exit={result.returncode}\n')
                        output.write(result.stdout + result.stderr)
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        result = subprocess.run(self.command('print-config', ordered) + ['--format=yaml'],
                                                env=self.env, capture_output=True, text=True, timeout=30)
                        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                        merged = yaml.safe_load(result.stdout)
                        self.assertEqual(set(merged['service']['pipelines']), expected_pipelines)
                        self.assertEqual(set(merged['service']['extensions']), expected_extensions)
                        self.assertEqual(set(merged['receivers']), expected_receivers)
                        self.assertEqual([j['job_name'] for j in merged['receivers']['prometheus']['config']['scrape_configs']],
                                         ['vllm', 'gpu-metrics'])
                        for name, pipeline in self.base['service']['pipelines'].items():
                            self.assertEqual(merged['service']['pipelines'][name], pipeline)
                        for product in ('milvus', 'qdrant'):
                            if product + '.yaml' in profiles:
                                pipeline = merged['service']['pipelines']['metrics/' + product]
                                self.assertEqual(pipeline['receivers'], ['prometheus/' + product])
                        if mode:
                            job = merged['receivers']['prometheus/litellm']['config']['scrape_configs'][0]
                            auth = job.get('authorization')
                            if mode == 'litellm-receiver.yaml':
                                self.assertEqual(auth['credentials_file'], self.env['LITELLM_METRICS_KEY_FILE'])
                                self.assertEqual(auth['type'], 'Bearer')
                            else:
                                self.assertIsNone(auth)
                count += 1
            output.write(f'PASS: {count} supported profile combinations; optional profiles checked in both orders.\n')
        self.assertEqual(count, 96)
        print(f'PASS: {count} profile combinations; pipelines, receivers and extensions preserved.', flush=True)

    def test_missing_metrics_key_fails_closed(self):
        env = dict(self.env, LITELLM_METRICS_KEY_FILE=str(self.directory / 'not-mounted'))
        result = subprocess.run(self.command('validate', ['litellm-receiver.yaml']), env=env,
                                capture_output=True, text=True, timeout=30)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('authorization credentials file', result.stderr)
        self.assertIn('no such file', result.stderr)
        (self.directory / 'missing-key.log').write_text(result.stdout + result.stderr)
        result = subprocess.run(self.command('validate', ['litellm-receiver-no-auth.yaml']), env=env,
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_base_without_products_has_no_scrape_or_connection_errors(self):
        EmptyKubernetes.requests = []
        EmptyKubernetes.closing.clear()
        server = ThreadingHTTPServer(('127.0.0.1', 0), EmptyKubernetes)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.addCleanup(EmptyKubernetes.closing.set)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        kubeconfig = self.directory / 'empty-kubeconfig.yaml'
        kubeconfig.write_text(yaml.safe_dump({
            'apiVersion': 'v1', 'kind': 'Config', 'current-context': 'fixture',
            'contexts': [{'name': 'fixture', 'context': {'cluster': 'fixture', 'user': 'fixture'}}],
            'clusters': [{'name': 'fixture', 'cluster': {'server': f'http://127.0.0.1:{server.server_port}'}}],
            'users': [{'name': 'fixture', 'user': {}}],
        }))
        config = copy.deepcopy(self.base)
        self.assertNotIn('elasticsearch', config['receivers'])
        self.assertNotIn('metrics/elasticsearch', config['service']['pipelines'])
        for job in config['receivers']['prometheus']['config']['scrape_configs']:
            self.assertNotIn('static_configs', job)
            job['kubernetes_sd_configs'][0]['kubeconfig_file'] = str(kubeconfig)
        config['processors']['k8s_attributes']['auth_type'] = 'kubeConfig'
        # Local ports/export replace only deployment-specific I/O; keep discovery,
        # relabel rules, processors, pipelines and the actual 10-second intervals.
        for receiver in ('otlp', 'jaeger'):
            for protocol in config['receivers'][receiver]['protocols'].values():
                protocol['endpoint'] = f'127.0.0.1:{free_port()}'
        health = f'127.0.0.1:{free_port()}'
        config['extensions']['health_check']['endpoint'] = health
        config['exporters'] = {'file/empty': {'path': str(self.directory / 'empty-metrics.jsonl')}}
        for pipeline in config['service']['pipelines'].values():
            pipeline['exporters'] = ['file/empty' if e == 'otlp' else e for e in pipeline['exporters']]
        config['service']['telemetry'] = {'logs': {'level': 'debug', 'encoding': 'json'}, 'metrics': {'level': 'none'}}
        path = self.directory / 'empty-config.yaml'
        path.write_text(yaml.safe_dump(config, sort_keys=False))
        env = dict(self.env, KUBECONFIG=str(kubeconfig))
        env.pop('ELASTICSEARCH_PASSWORD', None)
        log_path = self.directory / 'empty-products-collector.log'
        with log_path.open('w') as log:
            process = subprocess.Popen([OPTIONS.collector, '--config=' + str(path)], env=env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 25
                while time.monotonic() < deadline:
                    self.assertIsNone(process.poll(), log_path.read_text())
                    try:
                        with urllib.request.urlopen('http://' + health, timeout=1) as response:
                            if response.status == 200:
                                break
                    except OSError:
                        time.sleep(0.1)
                else:
                    self.fail('Collector did not become healthy: ' + log_path.read_text())
                # More than two full scrape intervals with valid empty discovery.
                time.sleep(22)
                self.assertIsNone(process.poll(), log_path.read_text())
            finally:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        content = log_path.read_text()
        self.assertEqual(process.returncode, 0, content)
        errors = [line for line in content.splitlines()
                  if ('"level":"error"' in line or '"level":"warn"' in line
                      or 'Failed to scrape' in line or 'connection refused' in line)
                  and 'alias is deprecated' not in line]
        self.assertEqual(errors, [], '\n'.join(errors))
        for namespace in ('ai-test', 'gpu-test'):
            for resource in ('pods', 'services', 'endpoints'):
                self.assertIn(f'/api/v1/namespaces/{namespace}/{resource}', EmptyKubernetes.requests)
        (self.directory / 'empty-kubernetes-requests.json').write_text(json.dumps(EmptyKubernetes.requests, indent=2) + '\n')
        print('PASS: base with empty Kubernetes API, 22s after readiness, no scrape/connection errors or static product inputs (existing processor alias warning excluded).', flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--collector', required=True)
    parser.add_argument('--evidence-dir')
    OPTIONS, remaining = parser.parse_known_args()
    unittest.main(argv=[__file__] + remaining, verbosity=2)
