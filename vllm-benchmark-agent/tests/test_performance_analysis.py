"""Unit tests for the metrics / analysis / dashboard pipeline.

No real containers, services or NPU traffic.
"""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT))
import benchmark  # noqa: E402
import config  # noqa: E402
import metrics  # noqa: E402
import perf  # noqa: E402
import agent.main as main  # noqa: E402


class PrometheusParsingTests(unittest.TestCase):
    def test_new_metric_names_and_aggregation(self):
        text = '\n'.join([
            'vllm:num_requests_waiting{model_name="m",engine="0"} 3',
            'vllm:num_requests_waiting{model_name="m",engine="1"} 2',
            'vllm:num_requests_waiting{model_name="other"} 99',
            'vllm:kv_cache_usage_perc{model_name="m",engine="0"} 0.4',
            'vllm:kv_cache_usage_perc{model_name="m",engine="1"} 0.9',
            'vllm:request_prefill_time_seconds_sum{model_name="m"} 5',
            'vllm:request_prefill_time_seconds_count{model_name="m"} 10',
            'vllm:request_prefill_time_seconds_bucket{model_name="m",le="0.3"} 4',
            'vllm:request_prefill_time_seconds_bucket{model_name="m",le="+Inf"} 10',
            'vllm:time_per_output_token_seconds_sum{model_name="m"} 1',
        ])
        parsed = metrics.parse_prometheus(text, 'm')
        # waiting sums across engines, model filtered
        self.assertEqual(parsed['vllm:num_requests_waiting'], 5)
        # kv usage takes the max across engines (pressure)
        self.assertEqual(parsed['vllm:kv_cache_usage_perc'], 0.9)
        # histograms keep sum/count and buckets
        self.assertEqual(parsed['vllm:request_prefill_time_seconds_count'], 10)
        self.assertEqual(parsed['vllm:request_prefill_time_seconds_buckets']['+Inf'], 10)
        # outdated metric name must not be picked up
        self.assertNotIn('vllm:time_per_output_token_seconds_sum', parsed)


class AnalyzeQueueTests(unittest.TestCase):
    def _samples(self):
        base = {
            'vllm:num_requests_running': 0.0,
            'vllm:num_requests_waiting': 0.0,
            'vllm:kv_cache_usage_perc': 0.1,
            'vllm:num_preemptions_total': 0.0,
            'vllm:prefix_cache_queries_total': 0.0,
            'vllm:prefix_cache_hits_total': 0.0,
            'vllm:request_queue_time_seconds_sum': 0.0,
            'vllm:request_queue_time_seconds_count': 0.0,
            'vllm:request_prefill_time_seconds_sum': 0.0,
            'vllm:request_prefill_time_seconds_count': 0.0,
            'vllm:time_to_first_token_seconds_sum': 0.0,
            'vllm:time_to_first_token_seconds_count': 0.0,
            'vllm:request_queue_time_seconds_buckets': {'0.3': 0.0, '+Inf': 0.0},
            'vllm:request_prefill_time_seconds_buckets': {'0.3': 0.0, '0.5': 0.0,
                                                          '0.8': 0.0, '+Inf': 0.0},
            'vllm:time_to_first_token_seconds_buckets': {'0.5': 0.0, '1.0': 0.0,
                                                         '+Inf': 0.0},
        }
        last = dict(base)
        last.update({
            'ts': 't1',
            'vllm:num_requests_running': 4.0,
            'vllm:num_requests_waiting': 10.0,
            'vllm:kv_cache_usage_perc': 0.5,
            'vllm:num_preemptions_total': 3.0,
            'vllm:prefix_cache_queries_total': 100.0,
            'vllm:prefix_cache_hits_total': 40.0,
            'vllm:request_queue_time_seconds_sum': 0.02,
            'vllm:request_queue_time_seconds_count': 10.0,
            'vllm:request_prefill_time_seconds_sum': 5.0,
            'vllm:request_prefill_time_seconds_count': 10.0,
            'vllm:time_to_first_token_seconds_sum': 6.0,
            'vllm:time_to_first_token_seconds_count': 10.0,
            'vllm:request_queue_time_seconds_buckets': {'0.3': 10.0, '+Inf': 10.0},
            'vllm:request_prefill_time_seconds_buckets': {'0.3': 2.0, '0.5': 8.0,
                                                          '0.8': 10.0, '+Inf': 10.0},
            'vllm:time_to_first_token_seconds_buckets': {'0.5': 3.0, '1.0': 10.0,
                                                         '+Inf': 10.0},
        })
        return [dict(base, ts='t0'), last]

    def test_server_summary_and_quantiles(self):
        summary = metrics.analyze_queue(self._samples())
        self.assertAlmostEqual(summary['mean_queue_time_ms'], 2.0, places=3)
        self.assertAlmostEqual(summary['mean_prefill_ms'], 500.0, places=3)
        self.assertAlmostEqual(summary['mean_ttft_ms'], 600.0, places=3)
        self.assertEqual(summary['avg_waiting'], 5.0)
        self.assertEqual(summary['max_waiting'], 10.0)
        self.assertEqual(summary['kv_cache_max'], 0.5)
        self.assertEqual(summary['preemptions'], 3.0)
        self.assertAlmostEqual(summary['prefix_cache_hit_rate'], 0.4, places=4)
        # prefill p50 interpolates inside the 0.3-0.5 bucket -> 0.4s
        self.assertAlmostEqual(summary['prefill_p50_ms'], 400.0, places=1)
        self.assertAlmostEqual(summary['prefill_p99_ms'], 785.0, places=1)


class BenchCommandTests(unittest.TestCase):
    def test_goodput_and_percentiles_flags(self):
        params = {'model': 'm', 'num_prompts': 10,
                  'metric_percentiles': '50,90,99',
                  'goodput': ['ttft:500', 'tpot:30']}
        cmd = benchmark.build_bench_command(params, '/tmp/x.json')
        self.assertEqual(cmd[cmd.index('--metric-percentiles') + 1], '50,90,99')
        index = cmd.index('--goodput')
        self.assertEqual(cmd[index + 1:index + 3], ['ttft:500', 'tpot:30'])

    def test_default_percentiles(self):
        cmd = benchmark.build_bench_command({'model': 'm', 'num_prompts': 1}, '/tmp/x.json')
        self.assertEqual(cmd[cmd.index('--metric-percentiles') + 1], '50,90,99')


class ConfigSweepTests(unittest.TestCase):
    def setUp(self):
        self.cfg = config.load(str(ROOT / 'tests' / 'fixtures' / 'benchmark.yaml'))

    def test_request_rates_and_metric_percentiles(self):
        cfg = copy.deepcopy(self.cfg)
        cfg['benchmark']['request_rates'] = [1, 2, 2]
        cfg['benchmark']['metric_percentiles'] = [90, 50, 99]
        config.normalize(cfg)
        self.assertEqual(cfg['benchmark']['request_rates'], [1.0, 2.0])
        self.assertEqual(cfg['benchmark']['metric_percentiles'], [50.0, 90.0, 99.0])

    def test_old_config_missing_new_sections_is_backfilled(self):
        cfg = copy.deepcopy(self.cfg)
        for key in ('slo',):
            cfg.pop(key, None)
        for key in ('request_rates', 'max_concurrency', 'metric_percentiles'):
            cfg['benchmark'].pop(key, None)
        config.normalize(cfg)
        self.assertIn('slo', cfg)
        self.assertEqual(cfg['benchmark']['metric_percentiles'], [50.0, 90.0, 99.0])

    def test_non_mapping_section_is_still_rejected(self):
        cfg = copy.deepcopy(self.cfg)
        cfg['slo'] = 'not-a-mapping'
        with self.assertRaises(ValueError):
            config.normalize(cfg)

    def test_invalid_sweep_values_are_rejected(self):
        for section, key, value in [
                ('benchmark', 'request_rates', ['x']),
                ('benchmark', 'metric_percentiles', []),
                ('benchmark', 'metric_percentiles', [150]),
                ('slo', 'ttft_ms', -1)]:
            cfg = copy.deepcopy(self.cfg)
            cfg[section][key] = value
            with self.subTest(key=key, value=value):
                with self.assertRaises(ValueError):
                    config.normalize(cfg)


class RoundSpecTests(unittest.TestCase):
    def test_concurrency_axis(self):
        rounds = main._round_specs({'concurrency': [1, 2], 'request_rate': None})
        self.assertEqual([r['id'] for r in rounds], ['benchmark.c1', 'benchmark.c2'])
        self.assertTrue(all(r['axis'] == 'concurrency' for r in rounds))

    def test_request_rate_takes_precedence(self):
        rounds = main._round_specs({'concurrency': [1], 'request_rates': [4, 8],
                                    'max_concurrency': 64})
        self.assertEqual([r['id'] for r in rounds], ['benchmark.q4', 'benchmark.q8'])
        self.assertTrue(all(r['axis'] == 'request_rate' for r in rounds))
        self.assertEqual(rounds[0]['request_rate'], 4)
        self.assertEqual(rounds[0]['concurrency'], 64)


class PerfAnalysisTests(unittest.TestCase):
    def _report(self):
        return {
            'run_id': 't', 'axis': 'concurrency',
            'config': {'model': {'name': 'm'}, 'slo': {'ttft_ms': 500.0}},
            'notes': [],
            'runs': [
                {'axis': 'concurrency', 'value': c, 'concurrency': c,
                 'label': 'c=%s' % c,
                 'metrics': {'bench': bench, 'queue': queue, 'quality': {'complete': True}}}
                for c, bench, queue in [
                    (1, {'mean_ttft_ms': 200.0, 'output_throughput': 100.0,
                         'request_throughput': 2.0, 'p99_ttft_ms': 300.0},
                     {'mean_queue_time_ms': 10.0, 'mean_prefill_ms': 150.0,
                      'avg_running': 1.0}),
                    (2, {'mean_ttft_ms': 400.0, 'output_throughput': 180.0,
                         'request_throughput': 3.5, 'p99_ttft_ms': 600.0},
                     {'mean_queue_time_ms': 20.0, 'mean_prefill_ms': 300.0,
                      'avg_running': 2.0}),
                ]
            ],
        }

    def test_rows_breakdown_and_slo(self):
        analysis = perf.analyze(self._report())
        first = analysis['rows'][0]
        self.assertEqual(first['label'], 'c=1')
        # other = mean_ttft - queue - prefill
        self.assertAlmostEqual(first['other_ms'], 40.0, places=3)
        self.assertTrue(first['slo_pass'])
        self.assertFalse(analysis['rows'][1]['slo_pass'])  # p99 600 > 500
        self.assertFalse(analysis['slo_defined'] is False)
        self.assertIn(analysis['summary']['max_output_throughput']['label'], ('c=2',))

    def test_parse_slo_short_and_long_keys(self):
        self.assertEqual(perf._parse_slo("ttft:15000,tpot:100"),
                         {"ttft_ms": 15000.0, "tpot_ms": 100.0})
        self.assertEqual(perf._parse_slo("ttft_ms:15000,e2el_ms:2000"),
                         {"ttft_ms": 15000.0, "e2el_ms": 2000.0})
        self.assertEqual(perf._parse_slo("unknown:5"), {})

    def test_saturation_detection(self):
        report = self._report()
        # make the 2nd level a plateau with a large TTFT jump
        report['runs'][1]['metrics']['bench']['output_throughput'] = 105.0
        report['runs'][1]['metrics']['bench']['p99_ttft_ms'] = 900.0
        analysis = perf.analyze(report)
        self.assertTrue(analysis['saturation']['detected'])
        self.assertEqual(analysis['saturation']['label'], 'c=2')

    def test_saturation_plateau_fallback(self):
        report = self._report()
        # throughput barely grows (<5%) while TTFT does not jump >50%
        report['runs'][1]['metrics']['bench']['output_throughput'] = 102.0
        report['runs'][1]['metrics']['bench']['p99_ttft_ms'] = 310.0
        sat = perf.analyze(report)['saturation']
        self.assertFalse(sat['detected'])
        self.assertTrue(sat.get('near_saturation'))
        self.assertEqual(sat['label'], 'c=2')

    def test_render_with_request_goodput_present(self):
        report = self._report()
        for run, gp in zip(report['runs'], (0.5, 1.2)):
            run['metrics']['bench']['request_goodput'] = gp
        with tempfile.TemporaryDirectory() as directory:
            report_path = os.path.join(directory, 'report.json')
            with open(report_path, 'w') as handle:
                json.dump(report, handle)
            png_path = os.path.join(directory, 'dash.png')
            result = perf.render(report_path, png_path,
                                 os.path.join(directory, 'a.json'))
            self.assertTrue(result['ok'])
            if result['data']['plot_path']:
                self.assertTrue(os.path.isfile(png_path))
            else:
                self.assertTrue(result['data']['plot_error'])

    def test_render_writes_analysis_and_optional_plot(self):
        report = self._report()
        with tempfile.TemporaryDirectory() as directory:
            report_path = os.path.join(directory, 'report.json')
            with open(report_path, 'w') as handle:
                json.dump(report, handle)
            analysis_path = os.path.join(directory, 'analysis.json')
            png_path = os.path.join(directory, 'dashboard.png')
            result = perf.render(report_path, png_path, analysis_path)
            self.assertTrue(result['ok'])
            self.assertTrue(os.path.isfile(analysis_path))
            # matplotlib may be absent in some environments; then plot_error is set.
            if result['data']['plot_path']:
                self.assertTrue(os.path.isfile(png_path))
            else:
                self.assertTrue(result['data']['plot_error'])


if __name__ == '__main__':
    unittest.main()
