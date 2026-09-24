"""Behavior tests: no real containers, services, or benchmark traffic."""
import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(ROOT))
import agent.main as main
from agent.workflow import Workflow
import config
import metrics
import benchmark
from common import ok, err


class WorkflowTests(unittest.TestCase):
    def test_metadata_roundtrip_and_reset(self):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, 'state.json')
            wf = Workflow(path)
            wf.set_meta(config={'port': 8001}, run_id='x')
            wf.transition('start')
            loaded = Workflow(path)
            self.assertEqual(loaded.meta['config']['port'], 8001)
            self.assertEqual(len(loaded.meta['history']), 1)
            loaded.reset()
            self.assertNotIn('config', Workflow(path).meta)

    def test_invalid_state_file_does_not_reset_to_idle(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'state.json'
            path.write_text('{broken')
            with self.assertRaises(ValueError):
                Workflow(str(path))

    def test_analyze_done_flows_through_stop_service(self):
        with tempfile.TemporaryDirectory() as directory:
            wf = Workflow(os.path.join(directory, 'state.json'))
            wf.state = 'ANALYZE'
            wf.transition('done')
            self.assertEqual(wf.current(), 'STOP_SERVICE')
            wf.transition('done')
            self.assertEqual(wf.current(), 'DONE')


class MetricsTests(unittest.TestCase):
    def test_labels_and_model_filter(self):
        text = '\n'.join([
            'vllm:num_requests_waiting{model_name="m",engine="0"} 3',
            'vllm:num_requests_waiting{model_name="m",engine="1"} 2',
            'vllm:num_requests_waiting{model_name="other"} 99',
            'vllm:request_queue_time_seconds_sum{model_name="m"} 2.5',
            'vllm:request_queue_time_seconds_count{model_name="m"} 5'])
        parsed = metrics.parse_prometheus(text, 'm')
        self.assertEqual(parsed['vllm:num_requests_waiting'], 5)
        self.assertEqual(parsed['vllm:request_queue_time_seconds_count'], 5)

    def test_missing_files_are_not_success(self):
        with tempfile.TemporaryDirectory() as directory:
            result = metrics.collect(directory + '/missing', directory + '/missing2')
            self.assertFalse(result['ok'])
            self.assertFalse(result['detail']['quality']['complete'])

    def test_counter_reset_is_not_a_valid_delta(self):
        self.assertIsNone(metrics._delta([{'count': 20}, {'count': 2}], 'count'))

    def test_selected_bench_only_does_not_require_queue(self):
        with tempfile.TemporaryDirectory() as directory:
            p = Path(directory) / 'bench.json'
            p.write_text(json.dumps({'output_throughput': 10, 'completed': 20}))
            result = metrics.collect(str(p), directory + '/noqueue', select=['throughput'])
            self.assertTrue(result['ok'])


class ConfigTests(unittest.TestCase):
    def setUp(self):
        self.cfg = config.load(str(ROOT / 'tests' / 'fixtures' / 'benchmark.yaml'))

    def test_invalid_values_are_not_silently_defaulted(self):
        for section, key, value in [('vllm', 'port', 'bad'), ('benchmark', 'requests', -1),
                                    ('metrics', 'interval', 0), ('vllm', 'gpu_memory_utilization', 1.5),
                                    ('benchmark', 'concurrency', [None])]:
            with self.subTest(key=key):
                cfg = copy.deepcopy(self.cfg)
                cfg[section][key] = value
                with self.assertRaises(ValueError):
                    config.normalize(cfg)

    def test_tp_and_context_must_fit_config(self):
        cfg = copy.deepcopy(self.cfg)
        cfg['vllm']['device'] = [2]
        cfg['vllm']['tensor_parallel_size'] = 2
        with self.assertRaises(ValueError):
            config.normalize(cfg)
        cfg = copy.deepcopy(self.cfg)
        cfg['vllm']['max_model_len'] = 10
        with self.assertRaises(ValueError):
            config.normalize(cfg)


    def test_served_model_name_validated_and_consistent(self):
        cfg = copy.deepcopy(self.cfg)
        cfg['vllm']['served_model_name'] = 'qwen3.5'
        config.normalize(cfg)
        self.assertEqual(cfg['vllm']['served_model_name'], 'qwen3.5')
        for bad in ('other', '   '):
            broken = copy.deepcopy(self.cfg)
            broken['vllm']['served_model_name'] = bad
            with self.assertRaises(ValueError):
                config.normalize(broken)


class ServedModelNameTests(unittest.TestCase):
    def setUp(self):
        self.cfg = config.load(str(ROOT / 'tests' / 'fixtures' / 'benchmark.yaml'))

    def test_resolve_client_model_prefers_explicit_field(self):
        cfg = copy.deepcopy(self.cfg)
        cfg['vllm']['served_model_name'] = 'qwen3.5'
        self.assertEqual(
            main._resolve_client_model(cfg, {'served_models': ['other']}),
            'qwen3.5')

    def test_launch_params_adds_served_model_name_when_missing(self):
        cfg = copy.deepcopy(self.cfg)
        cfg['vllm']['served_model_name'] = 'qwen3.5'
        cfg['vllm']['extra_args'] = ['--dtype', 'bfloat16']
        params = main._launch_params(
            main.build_parser().parse_args(['start']), cfg)
        self.assertEqual(
            params['extra_args'],
            ['--dtype', 'bfloat16', '--served-model-name', 'qwen3.5'])

    def test_launch_params_does_not_duplicate_served_model_name(self):
        cfg = copy.deepcopy(self.cfg)
        cfg['vllm']['served_model_name'] = 'qwen3.5'
        cfg['vllm']['extra_args'] = ['--served-model-name', 'qwen3.5']
        params = main._launch_params(
            main.build_parser().parse_args(['start']), cfg)
        self.assertEqual(params['extra_args'],
                         ['--served-model-name', 'qwen3.5'])


class LockHandoffTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        self.runs = self.dir / 'runs'
        self.locks = self.dir / 'locks'
        (self.runs / 'old_run').mkdir(parents=True)
        self.locks.mkdir()
        (self.runs / 'old_run' / 'state.json').write_text(
            json.dumps({'state': 'CANCELLED'}))
        meta = {'run_id': 'old_run', 'pid': 999999, 'devices': [2, 5]}
        (self.locks / 'npu_2.lock').write_text(json.dumps(dict(meta, device=2)))
        (self.locks / 'npu_5.lock').write_text(json.dumps(dict(meta, device=5)))
        for target, value in (('RUNS_DIR', str(self.runs)),
                              ('LOCKS_DIR', str(self.locks))):
            patcher = patch.object(main, target, value)
            patcher.start()
            self.addCleanup(patcher.stop)

    def _meta(self, run_id='old_run'):
        return {'run_id': run_id, 'pid': 999999, 'devices': [2, 5]}

    def test_terminal_owner_with_matching_service_is_reclaimable(self):
        probe = {'decision': 'already_running', 'device_match': True,
                 'npu_busy_physical': [2, 5]}
        self.assertFalse(main._lock_is_active(self._meta(), probe, 'new_run'))

    def test_terminal_owner_without_match_stays_active(self):
        probe = {'decision': 'device_busy', 'device_match': False,
                 'npu_busy_physical': [2, 5]}
        self.assertTrue(main._lock_is_active(self._meta(), probe, 'new_run'))

    def test_terminal_owner_with_free_device_is_not_active(self):
        probe = {'decision': 'need_start', 'device_match': False,
                 'npu_busy_physical': []}
        self.assertFalse(main._lock_is_active(self._meta(), probe, 'new_run'))

    def test_live_owner_stays_active(self):
        live = self.runs / 'live_run'
        live.mkdir(parents=True)
        (live / 'state.json').write_text(json.dumps({'state': 'BENCHMARK'}))
        meta = {'run_id': 'live_run', 'pid': os.getpid(), 'devices': [2, 5]}
        self.assertTrue(main._lock_is_active(meta, {}, 'new_run'))

    def test_try_acquire_takes_over_matching_terminal_lock(self):
        probe = {'decision': 'already_running', 'device_match': True,
                 'npu_busy_physical': [2, 5]}
        ok_, holders, acquired = main.device_lock.try_acquire(
            str(self.locks), [2, 5], 'new_run', pid=os.getpid(),
            is_active=lambda m: main._lock_is_active(m, probe, 'new_run'))
        self.assertTrue(ok_, holders)
        self.assertEqual(acquired, [2, 5])
        self.assertEqual(
            main.device_lock.snapshot(str(self.locks), [2, 5])[2]['run_id'],
            'new_run')

    def test_acquire_devices_records_handoff_audit(self):
        probe = {'decision': 'already_running', 'device_match': True,
                 'npu_busy_physical': [2, 5]}
        wf = main.Workflow(str(self.dir / 'newstate.json'))
        wf.reset()
        wf.set_meta(run_id='new_run',
                    config={'vllm': {'device': [2, 5], 'port': 8000},
                            'container': {'name': 'c'}})
        orig = main._current_run_id
        main._current_run_id = lambda: 'new_run'
        try:
            acquired, holders = main._acquire_devices(wf, probe)
        finally:
            main._current_run_id = orig
        self.assertTrue(acquired, holders)
        self.assertEqual([h['from_run'] for h in wf.meta['device_handoff']],
                         ['old_run', 'old_run'])


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        constants = {'DATA_ROOT': str(self.directory), 'STATE_DIR': str(self.directory),
                     'STATE_PATH': str(self.directory / 'state.json'),
                     'RUNS_DIR': str(self.directory / 'runs'),
                     'LOCKS_DIR': str(self.directory / 'locks'),
                     'CURRENT_RUN_PATH': str(self.directory / 'current_run'),
                     'UI_POINTER_PATH': str(self.directory / '.vllm-benchmark' / 'current.json'),
                     'UI_POINTER_PATHS': (str(self.directory / '.vllm-benchmark' / 'current.json'),)}
        for key, value in constants.items():
            patcher = patch.object(main, key, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.cfg = config.load(str(ROOT / 'tests' / 'fixtures' / 'benchmark.yaml'))
        self.cfg['benchmark']['concurrency'] = [1, 2]
        self.cfg['report']['output'] = str(self.directory / 'reports')
        self.calls = []
        self.launched = False
        self.conflict = False
        self.fail_level = None
        self.collect_failure = False
        self.container_stopped = False
        self.stop_failure = False
        self.saved_loader = main._load_config
        loader = patch.object(main, '_load_config', return_value=(copy.deepcopy(self.cfg), None))
        loader.start()
        self.addCleanup(loader.stop)
        runner = patch.object(main, 'call_tool', side_effect=self.tool)
        runner.start()
        self.addCleanup(runner.stop)
        test = self
        class Scraper:
            def __init__(self, argv, **kwargs):
                self.code = None
                self.path = argv[argv.index('--out') + 1]
                Path(self.path).write_text(json.dumps([{'ts': 'start', 'vllm:num_requests_waiting': 0}]))
            def poll(self):
                return self.code
            def send_signal(self, sig):
                self.code = 0
                test.calls.append(('scraper_stop', []))
            def wait(self, timeout=None):
                self.code = 0
                return 0
            def kill(self):
                self.code = -9
        popen = patch.object(main.subprocess, 'Popen', Scraper)
        popen.start()
        self.addCleanup(popen.stop)
        self.addCleanup(lambda: os.environ.pop('BENCHMARK_CANCEL_PATH', None))

    def args(self, *argv):
        return main.build_parser().parse_args(list(argv))

    def tool(self, script, argv, **kwargs):
        self.calls.append((script, argv))
        if script in ('environment.py', 'ascend.py', 'docker.py'):
            return ok({'checked': True})
        if script == 'vllm.py':
            if argv[0] == 'probe':
                port = argv[argv.index('--port') + 1]
                decision = 'container_stopped' if self.container_stopped else 'port_unavailable' if self.conflict and port == '8000' else 'already_running' if self.launched else 'need_start'
                return ok({'decision': decision, 'port': int(port)})
            if argv[0] == 'launch':
                self.launched = True
                return ok({'command': argv})
            if argv[0] == 'ensure':
                self.container_stopped = False
                return ok({'action': 'started'})
            if argv[0] == 'stop':
                if self.stop_failure:
                    return err('stop failed')
                return ok({'stopped': argv[argv.index('--name') + 1]})
        if script == 'benchmark.py':
            level = int(argv[argv.index('--max-concurrency') + 1])
            if level == self.fail_level:
                return err('failed round')
            path = self.directory / ('bench_%s.json' % level)
            path.write_text(json.dumps({'completed': 20, 'output_throughput': 100}))
            return ok({'result_path': str(path)})
        if script == 'metrics.py':
            if self.collect_failure:
                return err('missing queue', {'bench': {'output_throughput': 100}, 'quality': {'complete': False}})
            return ok({'bench': {'output_throughput': 100}, 'quality': {'complete': True}})
        raise AssertionError((script, argv))

    def test_normal_run_launches_without_confirmation(self):
        result = main.cmd_run(self.args('run'))
        self.assertTrue(result['ok'], result)
        self.assertEqual(main._wf().current(), 'ANALYZE')
        history = main._wf().meta['history']
        self.assertNotIn('WAIT_USER_DECISION', [x['to'] for x in history])
        self.assertEqual(sum(s == 'benchmark.py' for s, _ in self.calls), 2)
        self.assertTrue(any(s == 'vllm.py' and a[0] == 'launch' for s, a in self.calls))
        self.assertFalse(any(s == 'vllm.py' and a[0] == 'stop' for s, a in self.calls))
        self.assertTrue(Path(result['data']['report_output']).exists())
        tasks = main._read_tasks()
        self.assertEqual(
            {task['id']: task['status'] for task in tasks['benchmark_rounds']},
            {'benchmark.c1': 'completed', 'benchmark.c2': 'completed'},
        )
        rendered = main.render_tasks(tasks)
        self.assertIn('[✓] Benchmark', rendered)
        self.assertIn('并发 1', rendered)

    def test_existing_service_reused_without_launch_or_stop(self):
        self.launched = True
        result = main.cmd_run(self.args('run'))
        self.assertTrue(result['ok'])
        main.cmd_done(self.args('done'))
        self.assertEqual(main._wf().current(), 'DONE')
        self.assertFalse(any(s == 'vllm.py' and a[0] in ('launch', 'stop') for s, a in self.calls))

    def test_done_stops_service_started_this_run(self):
        result = main.cmd_run(self.args('run'))
        self.assertTrue(result['ok'], result)
        self.assertEqual(main._wf().current(), 'ANALYZE')
        self.assertTrue(any(s == 'vllm.py' and a[0] == 'launch' for s, a in self.calls))
        done = main.cmd_done(self.args('done'))
        self.assertTrue(done['ok'], done)
        self.assertEqual(main._wf().current(), 'DONE')
        self.assertTrue(done['data']['service_stopped'])
        self.assertTrue(any(s == 'vllm.py' and a[0] == 'stop' for s, a in self.calls))
        self.assertIsNone(main.device_lock.snapshot(main.LOCKS_DIR, [5])[5])

    def test_done_skips_stop_when_disabled(self):
        disabled = copy.deepcopy(self.cfg)
        disabled['cleanup']['stop_service'] = False
        main._load_config.return_value = (disabled, None)
        main.cmd_run(self.args('run'))
        done = main.cmd_done(self.args('done'))
        self.assertTrue(done['ok'], done)
        self.assertFalse(done['data']['service_stopped'])
        self.assertFalse(any(s == 'vllm.py' and a[0] == 'stop' for s, a in self.calls))

    def test_done_stop_failure_still_completes(self):
        self.stop_failure = True
        main.cmd_run(self.args('run'))
        done = main.cmd_done(self.args('done'))
        self.assertTrue(done['ok'], done)
        self.assertEqual(main._wf().current(), 'DONE')
        self.assertFalse(done['data']['service_stopped'])
        tasks = {task['id']: task['status'] for task in main._read_tasks()['tasks']}
        self.assertEqual(tasks['cleanup'], 'failed')

    def test_stopped_container_is_started_without_question(self):
        self.container_stopped = True
        result = main.cmd_run(self.args('run'))
        self.assertTrue(result['ok'])
        self.assertTrue(any(s == 'vllm.py' and a[0] == 'ensure' for s, a in self.calls))

    def test_conflict_only_asks_once_and_port_override_persists(self):
        self.conflict = True
        result = main.cmd_run(self.args('run'))
        self.assertTrue(result['needs_user_decision'])
        self.assertFalse(any(s == 'benchmark.py' for s, _ in self.calls))
        result = main.cmd_resume(self.args('resume', '--port', '8001'))
        self.assertTrue(result['ok'], result)
        for script, argv in self.calls:
            if script == 'benchmark.py' or script == 'vllm.py' and argv[0] == 'launch':
                self.assertEqual(argv[argv.index('--port') + 1], '8001')
        self.assertEqual(main._wf().meta['config']['vllm']['port'], 8001)

    def test_failed_round_resumes_without_repeating_completed_round(self):
        self.fail_level = 2
        result = main.cmd_run(self.args('run'))
        self.assertEqual(result['error'], 'benchmark_failed')
        self.fail_level = None
        result = main.cmd_resume(self.args('resume'))
        self.assertTrue(result['ok'])
        levels = [a[a.index('--max-concurrency') + 1] for s, a in self.calls if s == 'benchmark.py']
        self.assertEqual(levels, ['1', '2', '2'])

    def test_failed_round_is_visible_in_task_list(self):
        self.fail_level = 2
        main.cmd_run(self.args('run'))
        tasks = main._read_tasks()
        states = {task['id']: task['status'] for task in tasks['benchmark_rounds']}
        self.assertEqual(states['benchmark.c1'], 'completed')
        self.assertEqual(states['benchmark.c2'], 'failed')
        self.assertIn('benchmark_failed', main.render_tasks(tasks))

    def test_metrics_failure_recollects_without_rebenchmarking(self):
        self.collect_failure = True
        result = main.cmd_run(self.args('run'))
        self.assertEqual(result['error'], 'metrics_incomplete')
        self.collect_failure = False
        result = main.cmd_resume(self.args('resume'))
        self.assertTrue(result['ok'])
        self.assertEqual(sum(s == 'benchmark.py' for s, _ in self.calls), 2)

    def test_partial_metrics_require_explicit_acceptance(self):
        self.collect_failure = True
        main.cmd_run(self.args('run'))
        result = main.cmd_resume(self.args('resume', '--accept-partial'))
        # Only the saved first round was accepted. The next incomplete round blocks again.
        self.assertEqual(result['error'], 'metrics_incomplete')
        result = main.cmd_resume(self.args('resume', '--accept-partial'))
        self.assertTrue(result['ok'])
        self.assertFalse(result['data']['metrics']['quality']['complete'])

    def test_init_creates_independent_run_without_resetting_active(self):
        self.conflict = True
        main.cmd_run(self.args('run'))
        first_run = main._current_run_id()
        self.assertEqual(main._wf().current(), 'WAIT_USER_DECISION')
        result = main.cmd_init(self.args('init'))
        self.assertTrue(result['ok'], result)
        self.assertNotEqual(result['data']['run_id'], first_run)
        self.assertEqual(main._wf().current(), 'IDLE')
        # the previous run's own state must be untouched
        with open(os.path.join(main.RUNS_DIR, first_run, 'state.json')) as handle:
            self.assertEqual(json.load(handle)['state'], 'WAIT_USER_DECISION')

    def test_second_run_waits_while_npu_held_by_first(self):
        main.cmd_run(self.args('run'))
        first_run = main._current_run_id()
        self.assertEqual(main._wf().current(), 'ANALYZE')
        result = main.cmd_run(self.args('run'))
        self.assertEqual(result['data']['state'], 'WAITING_RESOURCE')
        self.assertEqual(result['data']['issue']['reason'], 'device_busy')
        self.assertNotEqual(main._current_run_id(), first_run)
        self.assertIn(first_run, json.dumps(result['data']['issue']['holders']))

    def test_different_npu_runs_are_independent(self):
        main.cmd_run(self.args('run', '--device', '2',
                               '--tensor-parallel-size', '1'))
        self.assertEqual(main._wf().current(), 'ANALYZE')
        result = main.cmd_run(self.args('run', '--device', '5',
                                        '--tensor-parallel-size', '1'))
        self.assertEqual(result['data']['state'], 'ANALYZE')
        held = main.device_lock.snapshot(main.LOCKS_DIR, [2, 5])
        self.assertIsNotNone(held[2])
        self.assertIsNotNone(held[5])

    def test_unhealthy_device_waits_instead_of_blocking(self):
        unhealthy = ok({'decision': 'device_unhealthy',
                        'inventory': {'devices': [{'id': 5, 'health': 'Alarm'}]}})
        with patch.object(main, '_run_probe', return_value=unhealthy):
            result = main.cmd_run(self.args('run'))
        self.assertEqual(result['data']['state'], 'WAITING_DEVICE')
        self.assertEqual(result['data']['issue']['reason'], 'device_unhealthy')
        self.assertEqual(main._wf().current(), 'WAITING_DEVICE')

    def test_resume_after_resource_released(self):
        main.cmd_run(self.args('run'))
        self.assertEqual(main._wf().current(), 'ANALYZE')
        waiting = main.cmd_run(self.args('run'))
        self.assertEqual(waiting['data']['state'], 'WAITING_RESOURCE')
        # simulate the owning service being stopped (it held both devices)
        main.device_lock.release_all(main.LOCKS_DIR, [2, 5])
        result = main.cmd_resume(self.args('resume'))
        self.assertTrue(result['ok'], result)
        self.assertEqual(main._wf().current(), 'ANALYZE')

    def test_stop_releases_device_locks(self):
        main.cmd_run(self.args('run'))
        self.assertIsNotNone(
            main.device_lock.snapshot(main.LOCKS_DIR, [5])[5])
        main.cmd_stop(self.args('stop'))
        self.assertIsNone(main.device_lock.snapshot(main.LOCKS_DIR, [5])[5])

    def test_run_id_option_targets_specific_run(self):
        main.cmd_run(self.args('run'))
        target = main._current_run_id()
        main._ACTIVE_RUN_OVERRIDE = target
        try:
            self.assertEqual(main._current_run_id(), target)
            status = main.cmd_status(self.args('status'))
            self.assertEqual(status['data']['run_id'], target)
        finally:
            main._ACTIVE_RUN_OVERRIDE = None

    def test_stop_defaults_to_frozen_target(self):
        self.conflict = True
        main.cmd_run(self.args('run'))
        result = main.cmd_stop(self.args('stop'))
        self.assertEqual(result['data']['stopped'], self.cfg['container']['name'])

    def test_configuration_stays_frozen_after_file_changes(self):
        self.conflict = True
        main.cmd_run(self.args('run'))
        main._load_config.return_value = (dict(self.cfg, vllm=dict(self.cfg['vllm'], port=9000)), None)
        self.conflict = False
        result = main.cmd_resume(self.args('resume'))
        self.assertTrue(result['ok'])
        self.assertEqual(main._wf().meta['config']['vllm']['port'], 8000)

    def test_cancel_blocked_run_preserves_service(self):
        self.conflict = True
        main.cmd_run(self.args('run'))
        result = main.cmd_cancel(self.args('cancel'))
        self.assertEqual(result['data']['state'], 'CANCELLED')
        self.assertFalse(any(s == 'vllm.py' and a[0] == 'stop' for s, a in self.calls))

    def test_cancel_release_locks_frees_devices(self):
        result = main.cmd_run(self.args('run'))
        self.assertTrue(result['ok'], result)
        self.assertIsNotNone(main.device_lock.snapshot(main.LOCKS_DIR, [5])[5])
        main.cmd_cancel(self.args('cancel', '--release-locks'))
        self.assertIsNone(main.device_lock.snapshot(main.LOCKS_DIR, [5])[5])

    def test_cancel_without_flag_keeps_locks(self):
        result = main.cmd_run(self.args('run'))
        self.assertTrue(result['ok'], result)
        main.cmd_cancel(self.args('cancel'))
        self.assertIsNotNone(main.device_lock.snapshot(main.LOCKS_DIR, [5])[5])

    def test_cancel_marker_prevents_execution(self):
        main.cmd_init(self.args('init'))
        Path(main._run_dir(), 'cancel').write_text('cancel')
        with self.assertRaises(KeyboardInterrupt):
            main._drive(self.args('run'))
        self.assertFalse(self.calls)

    def test_cli_can_fill_missing_model_before_validation(self):
        cfg = copy.deepcopy(self.cfg)
        cfg['model'] = {'name': None, 'path': None}
        main._load_config.return_value = (cfg, None)
        result = main.cmd_run(self.args('run', '--model', '/approved/model'))
        self.assertTrue(result['ok'], result)
        self.assertEqual(main._wf().meta['config']['model']['path'], '/approved/model')

    def test_loading_timeout_blocks_without_launching_again(self):
        def loading(*args):
            return ok({'decision': 'loading'})
        with patch.object(main, '_run_probe', side_effect=loading):
            result = main.cmd_run(self.args('run', '--health-retries', '1', '--health-wait', '0'))
        self.assertEqual(result['error'], 'service_health_timeout')
        self.assertFalse(any(s == 'vllm.py' and a[0] == 'launch' for s, a in self.calls))

    def test_health_wait_retries_transient_identity_unknown(self):
        # A one-off identity blip right after our own launch must not abort the
        # run: the health wait retries it instead of blocking immediately.
        seq = ['need_start', 'identity_unknown', 'loading', 'already_running']
        state = {'i': 0}

        def probe(*args, **kwargs):
            decision = seq[min(state['i'], len(seq) - 1)]
            state['i'] += 1
            return ok({'decision': decision})

        with patch.object(main, '_run_probe', side_effect=probe):
            result = main.cmd_run(self.args('run', '--health-retries', '5',
                                            '--health-wait', '0'))
        self.assertTrue(result['ok'], result)
        self.assertEqual(main._wf().current(), 'ANALYZE')
        self.assertNotIn('WAIT_USER_DECISION',
                         [x['to'] for x in main._wf().meta['history']])

    def test_identity_unknown_blocks_after_bounded_retries(self):
        # Persistent ambiguity (a real duplicate/foreign service) must still
        # block, after a bounded number of retries.
        state = {'i': 0}

        def probe(*args, **kwargs):
            decision = 'loading' if state['i'] == 0 else 'identity_unknown'
            state['i'] += 1
            return ok({'decision': decision})

        with patch.object(main, '_run_probe', side_effect=probe):
            result = main.cmd_run(self.args('run', '--health-retries', '10',
                                            '--health-wait', '0'))
        self.assertEqual(result['error'], 'identity_unknown')
        self.assertEqual(result['state'], 'WAIT_USER_DECISION')
        # 1 initial service probe + DEFAULT_IDENTITY_GRACE health retries
        self.assertEqual(state['i'], 1 + main.DEFAULT_IDENTITY_GRACE)

    def test_sampler_is_stopped_when_benchmark_raises(self):
        original = self.tool
        def broken(script, argv, **kwargs):
            if script == 'benchmark.py':
                raise RuntimeError('client exception')
            return original(script, argv, **kwargs)
        main.call_tool.side_effect = broken
        with self.assertRaises(RuntimeError):
            main.cmd_run(self.args('run'))
        self.assertIn(('scraper_stop', []), self.calls)

    def test_negative_timeout_is_rejected(self):
        result = main.cmd_run(self.args('run', '--timeout', '-1'))
        self.assertEqual(result['error'], 'configuration_invalid')
        self.assertFalse(any(s == 'vllm.py' for s, _ in self.calls))

    def test_request_rate_sweep_drives_request_rate_rounds(self):
        cfg = copy.deepcopy(self.cfg)
        cfg['benchmark']['concurrency'] = [1]
        cfg['benchmark']['request_rates'] = [4.0, 8.0]
        cfg['benchmark']['max_concurrency'] = 64
        main._load_config.return_value = (cfg, None)
        result = main.cmd_run(self.args('run'))
        self.assertTrue(result['ok'], result)
        bench_calls = [a for s, a in self.calls if s == 'benchmark.py']
        self.assertEqual(len(bench_calls), 2)
        self.assertEqual([a[a.index('--request-rate') + 1] for a in bench_calls],
                         ['4.0', '8.0'])
        for argv in bench_calls:
            self.assertEqual(argv[argv.index('--max-concurrency') + 1], '64')
            self.assertEqual(argv[argv.index('--metric-percentiles') + 1], '50.0,90.0,99.0')


class LocalBenchmarkTests(unittest.TestCase):
    def test_local_result_path_points_to_written_file(self):
        with tempfile.TemporaryDirectory() as directory:
            def fake_run(command, **kwargs):
                path = Path(command[command.index('--result-dir') + 1]) / command[command.index('--result-filename') + 1]
                path.write_text(json.dumps({'completed': 2}))
                return 0, '', ''
            with patch.object(benchmark, 'run', side_effect=fake_run):
                result = benchmark.run_bench({'model': 'm', 'local': True, 'result_dir': directory, 'num_prompts': 2})
            self.assertTrue(result['ok'])
            self.assertTrue(Path(result['data']['result_path']).is_file())


class DeviceLockTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.locks = os.path.join(self.temp.name, 'locks')

    def test_lock_is_mutually_exclusive(self):
        from tools import lock
        self.assertTrue(lock.try_acquire(self.locks, [5], 'run_a', pid=1,
                                         is_active=lambda m: True)[0])
        ok2, holders, acquired = lock.try_acquire(self.locks, [5], 'run_b', pid=2,
                                                  is_active=lambda m: True)
        self.assertFalse(ok2)
        self.assertEqual(acquired, [])
        self.assertEqual(holders[5]['run_id'], 'run_a')

    def test_stale_lock_is_reclaimed(self):
        from tools import lock
        lock.try_acquire(self.locks, [5], 'run_a', pid=1)
        ok2, _holders, acquired = lock.try_acquire(
            self.locks, [5], 'run_b', pid=2, is_active=lambda m: False)
        self.assertTrue(ok2)
        self.assertEqual(acquired, [5])
        self.assertEqual(lock.read_meta(lock.lock_path(self.locks, 5))['run_id'], 'run_b')

    def test_orphaned_run_lock_is_not_active(self):
        # A lock whose run directory no longer exists must not block others.
        with patch.object(main, 'RUNS_DIR', os.path.join(self.temp.name, 'runs')):
            self.assertFalse(main._lock_is_active(
                {'run_id': 'gone', 'devices': [5]}, {}, 'someone_else'))

    def test_release_only_for_owner(self):
        from tools import lock
        lock.try_acquire(self.locks, [5], 'run_a', pid=1)
        self.assertEqual(lock.release(self.locks, [5], 'run_b'), [])
        self.assertEqual(lock.release(self.locks, [5], 'run_a'), [5])
        self.assertIsNone(lock.read_meta(lock.lock_path(self.locks, 5)))

    def test_multi_device_all_or_nothing(self):
        from tools import lock
        lock.try_acquire(self.locks, [2], 'run_a', pid=1)
        ok2, holders, acquired = lock.try_acquire(
            self.locks, [2, 5], 'run_b', pid=2, is_active=lambda m: True)
        self.assertFalse(ok2)
        self.assertEqual(acquired, [])
        self.assertEqual(list(holders), [2])
        self.assertIsNone(lock.read_meta(lock.lock_path(self.locks, 5)))


if __name__ == '__main__':
    unittest.main()
