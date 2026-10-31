"""Scrape real LiteLLM with a mounted key and with public metrics (requires Docker)."""

import argparse
import json
import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parents[1]
OPTIONS = None
# SUSE's 1.81.13 image, pinned independently of moving tags.
IMAGE = ('registry.suse.com/ai/containers/litellm-database@'
         'sha256:7b9cbd3905f0d335630c2605b784e64ff69b6b2a0d12b3fc68f53dcf21fb6a97')
KEY = 'sk-collector-integration-test-not-a-secret'


def request(url, key=None):
    headers = {'Authorization': 'Bearer ' + key} if key else {}
    try:
        with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=5) as response:
            return response.status, response.read().decode()
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode()


class LiteLLMAuthentication(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if OPTIONS.evidence_dir:
            cls.directory = Path(OPTIONS.evidence_dir).resolve()
            cls.directory.mkdir(parents=True, exist_ok=True)
        else:
            cls.temp = tempfile.TemporaryDirectory(prefix='collector-litellm-')
            cls.addClassCleanup(cls.temp.cleanup)
            cls.directory = Path(cls.temp.name)
        cls.key_file = cls.directory / 'metrics-key'
        cls.key_file.write_text(KEY + '\n')
        cls.env = dict(os.environ, API_KEY='test-key', K8S_CLUSTER_NAME='test-cluster',
                       LITELLM_NAMESPACE='ai-test', LITELLM_SERVICE_NAME='litellm',
                       LITELLM_K8S_SERVICE_NAME='litellm-router',
                       LITELLM_METRICS_KEY_FILE=str(cls.key_file), OTEL_RESOURCE_ATTRIBUTES='')
        cls.urls = {}
        version = subprocess.check_output(['docker', 'run', '--rm', '--network=none', '--entrypoint=python',
                                           OPTIONS.image, '-c', 'import importlib.metadata; print(importlib.metadata.version("litellm"))'], text=True)
        (cls.directory / 'proxy-version.txt').write_text(OPTIONS.image + '\nLiteLLM ' + version)
        for mode in ('auth', 'public'):
            path = cls.directory / (mode + '-proxy.yaml')
            path.write_text(yaml.safe_dump({
                'model_list': [],
                'litellm_settings': {'callbacks': ['prometheus'],
                                     'require_auth_for_metrics_endpoint': mode == 'auth'},
                'general_settings': {'master_key': KEY},
            }))
            container = subprocess.check_output([
                'docker', 'run', '--detach', '--memory=1g', '--cpus=2', '--publish=127.0.0.1::4000',
                '--mount', f'type=bind,source={path},target=/app/collector-test-config.yaml,readonly',
                '--env=LITELLM_LOCAL_MODEL_COST_MAP=True', '--env=LITELLM_TELEMETRY=False',
                OPTIONS.image, '--config=/app/collector-test-config.yaml', '--port=4000'], text=True).strip()
            cls.addClassCleanup(cls.stop_proxy, container, mode)
            address = subprocess.check_output(['docker', 'port', container, '4000/tcp'], text=True).strip()
            url = 'http://' + address + '/metrics/'
            deadline = time.monotonic() + 90
            while time.monotonic() < deadline:
                try:
                    status, body = request(url, KEY)
                    if status == 200 and 'litellm_' in body:
                        cls.urls[mode] = url
                        break
                except OSError:
                    pass
                time.sleep(0.25)
            else:
                logs = subprocess.run(['docker', 'logs', container], capture_output=True, text=True).stdout
                raise AssertionError('LiteLLM did not become ready: ' + logs)

    @classmethod
    def stop_proxy(cls, container, mode):
        logs = subprocess.run(['docker', 'logs', container], capture_output=True, text=True)
        (cls.directory / (mode + '-proxy.log')).write_text(logs.stdout + logs.stderr)
        subprocess.run(['docker', 'rm', '--force', container], capture_output=True, check=True)

    def scrape(self, mode, key_file, *, expected_up):
        profile = 'litellm-receiver.yaml' if mode == 'auth' else 'litellm-receiver-no-auth.yaml'
        env = dict(self.env, LITELLM_METRICS_KEY_FILE=str(key_file))
        result = subprocess.run([OPTIONS.collector, 'validate', '--config=' + str(ROOT / 'collector-config.yaml'),
                                 '--config=' + str(ROOT / profile)], env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        base = yaml.safe_load((ROOT / 'collector-config.yaml').read_text())
        config = yaml.safe_load((ROOT / profile).read_text())
        config['processors'] = {**base['processors'], **config['processors']}
        config['processors']['batch'] = {'timeout': '1s'}
        pipeline = config['service']['pipelines']['metrics/litellm']
        # Run the real profile/processor chain. Only local discovery, interval and
        # export destination replace their Kubernetes/deployment counterparts.
        target = self.urls[mode].split('/')[2]
        env['LITELLM_METRICS_PORT'] = target.rsplit(':', 1)[1]
        discovery = self.directory / (self.id().split('.')[-1] + '-discovery.json')
        discovery.write_text(json.dumps([{'targets': [target], 'labels': {
            '__meta_kubernetes_service_name': 'litellm-router',
            '__meta_kubernetes_pod_uid': 'real-litellm-proxy-pod',
            '__meta_kubernetes_pod_name': 'litellm-test',
            '__meta_kubernetes_pod_node_name': 'test-node',
        }}]))
        job = config['receivers']['prometheus/litellm']['config']['scrape_configs'][0]
        job.pop('kubernetes_sd_configs')
        job['file_sd_configs'] = [{'files': [str(discovery)]}]
        job['scrape_interval'], job['scrape_timeout'] = '1s', '1s'
        output = self.directory / (self.id().split('.')[-1] + '-metrics.jsonl')
        output.unlink(missing_ok=True)
        config['exporters'] = {'file/test': {'path': str(output), 'format': 'json', 'flush_interval': '100ms'}}
        pipeline['exporters'] = ['file/test']
        config['service']['telemetry'] = {'metrics': {'level': 'none'}}
        path = self.directory / (self.id().split('.')[-1] + '-collector.yaml')
        path.write_text(yaml.safe_dump(config, sort_keys=False))
        log_path = path.with_suffix('.log')
        found = {}
        with log_path.open('w') as log:
            process = subprocess.Popen([OPTIONS.collector, '--config=' + str(path)], env=env, stdout=log, stderr=log)
            try:
                deadline = time.monotonic() + 20
                while time.monotonic() < deadline:
                    self.assertIsNone(process.poll(), log_path.read_text())
                    if output.exists():
                        for line in output.read_text().splitlines():
                            try:
                                batch = json.loads(line)
                            except json.JSONDecodeError:
                                continue  # The file exporter can be mid-write.
                            for resource in batch.get('resourceMetrics', []):
                                for scope in resource.get('scopeMetrics', []):
                                    for metric in scope.get('metrics', []):
                                        for point in metric.get('gauge', {}).get('dataPoints', []):
                                            found[metric['name']] = float(point.get('asInt', point.get('asDouble', -1)))
                    if found.get('up') == expected_up and (expected_up == 0 or 'python_info' in found):
                        break
                    time.sleep(0.1)
                self.assertEqual(found.get('up'), expected_up, log_path.read_text())
                if expected_up:
                    self.assertIn('python_info', found, 'No real proxy metrics exported')
                else:
                    self.assertIn('401', log_path.read_text())
            finally:
                if process.poll() is None:
                    process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)
        self.assertEqual(process.returncode, 0, log_path.read_text())
        print(f'PASS: LiteLLM {mode}, Collector up={expected_up}, key file exists={key_file.exists()}', flush=True)

    def test_auth_on_reads_mounted_key(self):
        self.assertEqual(request(self.urls['auth'])[0], 401)
        self.assertEqual(request(self.urls['auth'], KEY)[0], 200)
        self.scrape('auth', self.key_file, expected_up=1)

    def test_auth_off_works_without_key_file(self):
        missing = self.directory / 'not-mounted'
        self.assertFalse(missing.exists())
        self.assertEqual(request(self.urls['public'])[0], 200)
        self.scrape('public', missing, expected_up=1)

    def test_wrong_key_is_rejected(self):
        wrong = self.directory / 'wrong-key'
        wrong.write_text('sk-wrong-collector-test-key\n')
        self.scrape('auth', wrong, expected_up=0)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--collector', required=True)
    parser.add_argument('--image', default=IMAGE)
    parser.add_argument('--evidence-dir')
    OPTIONS, remaining = parser.parse_known_args()
    unittest.main(argv=[__file__] + remaining, verbosity=2)
