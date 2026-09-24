#!/usr/bin/env python3
"""Scope + device-mapping tests for the vLLM benchmark agent.

Verifies the agent never creates/deletes containers (no `docker run`/`rm`),
that benchmark.yaml `vllm.device` (physical ids) is converted to the container
logical ids used by ASCEND_RT_VISIBLE_DEVICES, and the probe/launch helpers.
"""

import contextlib
import io
import json
import os
import shlex
import sys
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TOOLS = os.path.join(ROOT, "tools")
for p in (ROOT, TOOLS):
    if p not in sys.path:
        sys.path.insert(0, p)

import vllm  # noqa: E402  (tools/vllm.py)
import benchmark  # noqa: E402  (tools/benchmark.py)
import agent.main as main  # noqa: E402


NPU_SMI_BUSY = """+------------------------------------------------------------------+
| NPU   Name | Health | Power(W) Temp(C) Hugepages-Usage(page) |
| Chip | Bus-Id | AICore(%) Memory-Usage(MB) HBM-Usage(MB) |
+==================================================================+
| 2     910B4-1 | OK | 70.1 36 0/0 |
| 0 | 0000:18:00.0 | 0 0/0 57931/65536 |
+==================================================================+
| 5     910B4-1 | OK | 76.1 37 0/0 |
| 0 | 0000:96:00.0 | 0 0/0 3413/65536 |
+==================================================================+
| NPU Chip | Process id | Process name | Process memory(MB) | Process id in container |
+==================================================================+
| 2       0 | 3246291 |  | 54566 | 261307 |
+==================================================================+
| No running processes found in NPU 5 |
"""

NPU_SMI_FREE = """+------------------------------------------------------------------+
| NPU   Name | Health | Power(W) Temp(C) Hugepages-Usage(page) |
| Chip | Bus-Id | AICore(%) Memory-Usage(MB) HBM-Usage(MB) |
+==================================================================+
| 2     910B4-1 | OK | 70.1 36 0/0 |
| 0 | 0000:18:00.0 | 0 0/0 3418/65536 |
+==================================================================+
| 5     910B4-1 | OK | 76.1 37 0/0 |
| 0 | 0000:96:00.0 | 0 0/0 3413/65536 |
+==================================================================+
| NPU Chip | Process id | Process name | Process memory(MB) | Process id in container |
+==================================================================+
| No running processes found in NPU 2 |
| No running processes found in NPU 5 |
"""


class VllmEnsureTests(unittest.TestCase):
    def test_ensure_commands_have_no_run(self):
        inspect_cmd, start_cmd = vllm.build_ensure_commands("qwen-bench5")
        self.assertEqual(inspect_cmd[:2], ["docker", "inspect"])
        self.assertEqual(start_cmd, ["docker", "start", "qwen-bench5"])
        self.assertNotIn("run", inspect_cmd)
        self.assertNotIn("run", start_cmd)

    def test_no_run_helpers_remain(self):
        self.assertFalse(hasattr(vllm, "build_run_command"))
        self.assertFalse(hasattr(vllm, "start"))

    def test_ensure_missing_container(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return (1, "", "Error: No such object: qwen-bench5")

        orig = vllm.run
        vllm.run = fake_run
        try:
            res = vllm.ensure("qwen-bench5")
        finally:
            vllm.run = orig
        self.assertFalse(res["ok"])
        self.assertEqual(res["detail"]["code"], "container_not_found")
        self.assertEqual(len(calls), 1)  # only inspect, never start/run

    def test_ensure_already_running(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return (0, "true\n", "")

        orig = vllm.run
        vllm.run = fake_run
        try:
            res = vllm.ensure("qwen-bench5")
        finally:
            vllm.run = orig
        self.assertTrue(res["ok"])
        self.assertEqual(res["data"]["action"], "already_running")
        self.assertEqual(len(calls), 1)  # inspect only

    def test_ensure_stopped_starts(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            if cmd[1] == "inspect":
                return (0, "false\n", "")
            return (0, "qwen-bench5\n", "")

        orig = vllm.run
        vllm.run = fake_run
        try:
            res = vllm.ensure("qwen-bench5")
        finally:
            vllm.run = orig
        self.assertTrue(res["ok"])
        self.assertEqual(res["data"]["action"], "started")
        self.assertIn(["docker", "start", "qwen-bench5"], calls)

    def test_ensure_no_start_flag(self):
        def fake_run(cmd, **kw):
            return (0, "false\n", "")

        orig = vllm.run
        vllm.run = fake_run
        try:
            res = vllm.ensure("qwen-bench5", start_if_stopped=False)
        finally:
            vllm.run = orig
        self.assertFalse(res["ok"])
        self.assertEqual(res["detail"]["code"], "container_not_running")

    def test_stop_never_removes(self):
        calls = []

        def fake_run(cmd, **kw):
            calls.append(cmd)
            return (0, "qwen-bench5\n", "")

        orig = vllm.run
        vllm.run = fake_run
        try:
            res = vllm.stop("qwen-bench5")
        finally:
            vllm.run = orig
        self.assertTrue(res["ok"])
        self.assertFalse(res["data"]["removed"])
        for cmd in calls:
            self.assertNotIn("rm", cmd)


class DeviceMappingTests(unittest.TestCase):
    def test_parse_davinci_ids_ignores_manager_and_sorts(self):
        text = "/dev/davinci5\n/dev/davinci_manager\n/dev/davinci2\n"
        self.assertEqual(vllm.parse_davinci_ids(text), [2, 5])
        self.assertEqual(vllm.parse_davinci_ids(""), [])

    def test_physical_to_logical(self):
        self.assertEqual(
            vllm.physical_to_logical([2, 5], [2]), ([0], [], {2: 0, 5: 1}))
        self.assertEqual(
            vllm.physical_to_logical([2, 5], [5]), ([1], [], {2: 0, 5: 1}))
        self.assertEqual(
            vllm.physical_to_logical([2, 5], [2, 5]), ([0, 1], [], {2: 0, 5: 1}))
        # physical id not visible -> reported missing, not silently mapped
        self.assertEqual(
            vllm.physical_to_logical([2, 5], [0]), ([], [0], {2: 0, 5: 1}))


class LaunchCommandTests(unittest.TestCase):
    def test_build_serve_command(self):
        params = {
            "model": "/home/models/M/", "host": "0.0.0.0", "port": 8000,
            "tensor_parallel_size": 1, "max_model_len": 32768,
            "gpu_memory_utilization": 0.9,
            "extra_args": ["--trust-remote-code", "--max-num-seqs", "128"],
        }
        cmd = vllm.build_serve_command(params)
        self.assertEqual(cmd[:3], ["vllm", "serve", "/home/models/M/"])
        self.assertIn("--port", cmd)
        self.assertIn("--tensor-parallel-size", cmd)
        self.assertIn("--max-model-len", cmd)
        self.assertIn("--gpu-memory-utilization", cmd)
        self.assertIn("--trust-remote-code", cmd)

    def test_build_launch_command_exec_detached_logical(self):
        serve = ["vllm", "serve", "/m", "--port", "8000"]
        cmd = vllm.build_launch_command(
            "qwen-bench-hs", serve, logical_devices=[0],
            log_path="/tmp/vllm_serve_x.log")
        self.assertEqual(cmd[:3], ["docker", "exec", "-d"])
        self.assertIn("-e", cmd)
        self.assertIn("ASCEND_RT_VISIBLE_DEVICES=0", cmd)
        self.assertIn("qwen-bench-hs", cmd)
        self.assertIn("bash", cmd)
        self.assertNotIn("run", cmd)
        self.assertNotIn("rm", cmd)
        # physical ids must NOT leak into the exec env
        self.assertNotIn("ASCEND_RT_VISIBLE_DEVICES=2", cmd)

    def test_launch_missing_physical_is_error(self):
        def fake_run(cmd, **kw):
            return (0, "/dev/davinci2\n/dev/davinci5\n", "")

        orig = vllm.run
        vllm.run = fake_run
        try:
            res = vllm.launch("c", ["vllm", "serve", "/m"],
                              physical_ids=[0])
        finally:
            vllm.run = orig
        self.assertFalse(res["ok"])
        self.assertEqual(res["detail"]["missing"], [0])


# main `vllm serve` root 260657 + NPU-holding child `VLLM::EngineCore` 261307
VLLM_PS = (
    "root      260657       0  0 01:08 ?        00:00:33 "
    "/usr/local/python3.12.13/bin/python3 "
    "/usr/local/python3.12.13/bin/vllm serve /home/models/M/ --port 8000\n"
    "root      261307  260657 11 01:08 ?        00:06:47 VLLM::EngineCore\n")


class ProbeTests(unittest.TestCase):
    def _patch(self, smi, health_ok=True, model_id="/home/models/M/",
               ps=VLLM_PS, proc=None):
        orig_run, orig_http = vllm.run, vllm._http_get

        def fake_run(cmd, **kw):
            joined = " ".join(str(c) for c in cmd)
            if "inspect" in cmd:
                return (0, "true\n", "")
            if "davinci" in joined:
                return (0, "/dev/davinci2\n/dev/davinci5\n", "")
            if "ps" in cmd:
                normalized = "\n".join(" ".join([line.split(None, 7)[1], line.split(None, 7)[2], line.split(None, 7)[7]]) for line in ps.splitlines())
                return (0, normalized, "")
            if "/cmdline" in joined:
                return (0, proc or "", "")
            if "python3" in cmd and "urllib.request" in joined:
                status, body = fake_http("/v1/models" if "/v1/models" in joined else "/health")
                return (0, str(status) + "\n" + body, "") if status else (1, "", "refused")
            if "npu-smi" in joined:
                return (0, smi, "")
            return (0, "", "")

        def fake_http(url, timeout=10):
            if url.endswith("/health"):
                return (200, "") if health_ok else (None, "refused")
            if url.endswith("/v1/models"):
                return (200, json.dumps({"data": [{"id": model_id}]}))
            return (None, "err")

        vllm.run = fake_run
        vllm._http_get = fake_http
        return (orig_run, orig_http)

    def _unpatch(self, orig):
        vllm.run, vllm._http_get = orig

    def test_probe_already_running_on_target(self):
        # vLLM process 261307 holds physical NPU 2; requested NPU 2 -> on target
        orig = self._patch(NPU_SMI_BUSY, health_ok=True)
        try:
            res = vllm.probe("c", port=8000, model="/home/models/M/",
                             physical_ids=[2])
        finally:
            self._unpatch(orig)
        self.assertTrue(res["ok"])
        self.assertEqual(res["data"]["decision"], "already_running")
        self.assertEqual(res["data"]["logical_devices"], [0])
        self.assertEqual(res["data"]["device_map"], {2: 0, 5: 1})
        self.assertEqual(res["data"]["vllm_physical_devices"], [2])

    def test_probe_device_mismatch(self):
        # same model + healthy port, but vLLM runs on NPU 2 while yaml says NPU 5
        orig = self._patch(NPU_SMI_BUSY, health_ok=True)
        try:
            res = vllm.probe("c", port=8000, model="/home/models/M/",
                             physical_ids=[5])
        finally:
            self._unpatch(orig)
        self.assertTrue(res["ok"])
        self.assertEqual(res["data"]["decision"], "device_mismatch")
        self.assertEqual(res["data"]["device_match"], False)
        self.assertEqual(res["data"]["logical_devices"], [1])

    def test_probe_need_start_when_npu_free(self):
        orig = self._patch(NPU_SMI_FREE, health_ok=False, ps="")
        try:
            res = vllm.probe("c", port=8000, model="/home/models/M/",
                             physical_ids=[2])
        finally:
            self._unpatch(orig)
        self.assertTrue(res["ok"])
        self.assertEqual(res["data"]["decision"], "need_start")

    def test_probe_loading_when_npu_busy_but_not_healthy(self):
        orig = self._patch(NPU_SMI_BUSY, health_ok=False)
        try:
            res = vllm.probe("c", port=8000, model="/home/models/M/",
                             physical_ids=[2])
        finally:
            self._unpatch(orig)
        self.assertEqual(res["data"]["decision"], "loading")

    def test_probe_partial_device_occupancy_while_loading_is_transient(self):
        # Only NPU 2 shows a worker yet (NPU 5 requested too) and the endpoint
        # is not healthy: this is startup, not a real device mismatch.
        orig = self._patch(NPU_SMI_BUSY, health_ok=False)
        try:
            res = vllm.probe("c", port=8000, model="/home/models/M/",
                             physical_ids=[2, 5])
        finally:
            self._unpatch(orig)
        self.assertEqual(res["data"]["decision"], "loading")

    def test_probe_port_conflict_different_model(self):
        orig = self._patch(NPU_SMI_FREE, health_ok=True, model_id="/other/")
        try:
            res = vllm.probe("c", port=8000, model="/home/models/M/",
                             physical_ids=[2])
        finally:
            self._unpatch(orig)
        self.assertEqual(res["data"]["decision"], "model_mismatch")

    def test_probe_groups_launcher_and_child_roots(self):
        # A launcher shell and the process it exec's are the same logical
        # service; the duplicated `vllm serve` argv must not be reported as an
        # ambiguous (foreign) service.
        ps = (
            "root 260657 0 0 01:08 ? 00:00:33 "
            "bash -lc exec vllm serve /home/models/M/ --port 8000\n"
            "root 261307 260657 0 01:08 ? 00:00:33 "
            "/usr/bin/python3 /usr/bin/vllm serve /home/models/M/ --port 8000\n"
            "root 261999 261307 11 01:08 ? 00:06:47 VLLM::EngineCore\n")
        orig = self._patch(NPU_SMI_BUSY, health_ok=False, ps=ps)
        try:
            res = vllm.probe("c", port=8000, model="/home/models/M/",
                             physical_ids=[2])
        finally:
            self._unpatch(orig)
        data = res["data"]
        self.assertEqual(data["decision"], "loading")
        self.assertEqual(data["root_count"], 2)
        self.assertEqual(data["root_pids"], [260657, 261307])
        self.assertEqual(data["service_pid"], 260657)
        self.assertEqual(data["vllm_physical_devices"], [2])

    def test_probe_independent_roots_stay_ambiguous(self):
        # Two unrelated services on the same port with no NPU ownership info:
        # the probe must refuse to guess.
        ps = (
            "root 300 0 0 01:08 ? 00:00:33 "
            "/usr/bin/vllm serve /home/models/M/ --port 8000\n"
            "root 500 0 0 01:08 ? 00:00:33 "
            "/usr/bin/vllm serve /home/models/M/ --port 8000\n")
        orig = self._patch(NPU_SMI_FREE, health_ok=False, ps=ps)
        try:
            res = vllm.probe("c", port=8000, model="/home/models/M/",
                             physical_ids=[2])
        finally:
            self._unpatch(orig)
        data = res["data"]
        self.assertEqual(data["decision"], "identity_unknown")
        self.assertEqual(data["root_count"], 2)
        self.assertEqual(data["root_groups"], [[300], [500]])


    def test_probe_prefers_exact_proc_cmdline_for_json_options(self):
        # `ps` drops shell quoting and splits JSON values; /proc/<pid>/cmdline
        # keeps the exact argv, so JSON-valued options must compare equal.
        proc = "\n".join([
            "/usr/local/python3.12.13/bin/python3",
            "/usr/local/python3.12.13/bin/vllm",
            "serve", "/home/models/M/",
            "--host", "0.0.0.0", "--port", "8000",
            "--tensor-parallel-size", "2",
            "--max-model-len", "133000",
            "--gpu-memory-utilization", "0.9",
            "--speculative-config",
            '{"method": "qwen3_5_mtp", "num_speculative_tokens": 3, "enforce_eager": true}',
            "--compilation-config", '{"cudagraph_mode":"FULL_DECODE_ONLY"}',
            "--additional-config", '{"enable_cpu_binding":true}',
        ])
        expected = {
            "tensor_parallel_size": 2,
            "max_model_len": 133000,
            "gpu_memory_utilization": 0.9,
            "extra_args": [
                "--speculative-config",
                '{"method": "qwen3_5_mtp", "num_speculative_tokens": 3, "enforce_eager": true}',
                "--compilation-config", '{"cudagraph_mode":"FULL_DECODE_ONLY"}',
                "--additional-config", '{"enable_cpu_binding":true}',
            ],
        }
        orig = self._patch(NPU_SMI_BUSY, health_ok=True, proc=proc)
        try:
            res = vllm.probe("c", port=8000, model="/home/models/M/",
                             physical_ids=[2], expected=expected)
        finally:
            self._unpatch(orig)
        data = res["data"]
        self.assertEqual(data["decision"], "already_running",
                         data.get("mismatches"))
        self.assertIsNone(data.get("mismatches"))
        self.assertEqual(
            data["actual_options"]["--speculative-config"],
            '{"method": "qwen3_5_mtp", "num_speculative_tokens": 3, "enforce_eager": true}')


class WorkflowTests(unittest.TestCase):
    def test_new_states_and_transitions(self):
        from agent.workflow import load_definition
        d = load_definition(os.path.join(ROOT, "workflow", "benchmark.yaml"))
        for st in ("PROBE_SERVICE", "WAIT_USER_DECISION", "START_SERVICE", "FAILED"):
            self.assertIn(st, d["states"])
        edges = {(t["from"], t["event"]): t["to"] for t in d["transitions"]}
        self.assertEqual(edges[("REPORT", "continue")], "PROBE_SERVICE")
        self.assertEqual(edges[("PROBE_SERVICE", "already_running")], "HEALTH")
        self.assertEqual(edges[("PROBE_SERVICE", "need_start")], "START_SERVICE")
        self.assertEqual(edges[("PROBE_SERVICE", "block")], "WAIT_USER_DECISION")
        self.assertEqual(edges[("START_SERVICE", "done")], "HEALTH")
        self.assertEqual(edges[("HEALTH", "fail")], "FAILED")


class VisibleDevicesTests(unittest.TestCase):
    def test_exec_command_uses_logical_ids(self):
        bench_cmd = ["vllm", "bench", "serve", "--model", "m"]
        params = {"container": "qwen-bench5", "runtime": "docker",
                  "visible_devices": "0,1"}
        cmd = benchmark.build_exec_command(params, bench_cmd)
        self.assertIn("exec", cmd)
        self.assertNotIn("run", cmd)
        self.assertIn("ASCEND_RT_VISIBLE_DEVICES=0,1", cmd)
        # docker exec options (-e ENV) precede the container name
        self.assertEqual(cmd[cmd.index("exec") + 3], "qwen-bench5")


class ConfigTests(unittest.TestCase):
    def test_no_image_field_and_physical_device(self):
        cfg = main._load_config(main.DEFAULT_CONFIG)[0]
        # container.image removed from file -> DEFAULTS backfills None
        self.assertIsNone(cfg["container"].get("image"))
        # vllm.device holds physical NPU ids (list[int]); value is user-owned
        dev = cfg["vllm"]["device"]
        self.assertIsInstance(dev, list)
        self.assertTrue(all(isinstance(x, int) for x in dev))


class BugRegressionTests(unittest.TestCase):
    """Regression tests for the two bugs found during live validation."""

    # Bug 1: `--extra-arg --flag` made argparse treat `--flag` as an option,
    # so `vllm.py launch` exited rc=2. Values must use the `=` form.
    def test_extra_arg_uses_equals_form(self):
        params = {
            "model": "/m", "port": 8001, "host": "0.0.0.0", "physical": [5],
            "tensor_parallel_size": 1, "max_model_len": 32768,
            "gpu_memory_utilization": 0.9,
            "extra_args": ["--trust-remote-code", "--max-num-seqs", "128"],
        }
        argv = main._build_launch_args("qwen-bench-hs", "docker", params,
                                       "/tmp/x.log")
        self.assertNotIn("--extra-arg", argv)  # never a bare flag
        self.assertIn("--extra-arg=--trust-remote-code", argv)
        self.assertIn("--extra-arg=--max-num-seqs", argv)
        self.assertIn("--extra-arg=128", argv)

    def test_launch_cli_parses_equals_form_extra_args(self):
        argv = main._build_launch_args("c", "docker", {
            "model": "/m", "port": 8001, "host": "0.0.0.0", "physical": [5],
            "tensor_parallel_size": 1, "max_model_len": 32768,
            "gpu_memory_utilization": 0.9,
            "extra_args": ["--trust-remote-code", "--max-num-seqs", "128"],
        }, "/tmp/x.log")
        captured = {}

        def fake_launch(name, serve_cmd, **kw):
            captured["serve_cmd"] = serve_cmd
            return {"ok": True, "data": {}}

        orig_launch, orig_argv = vllm.launch, sys.argv
        vllm.launch = fake_launch
        sys.argv = ["vllm.py"] + argv
        try:
            with contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaises(SystemExit):
                    vllm.main()
        finally:
            vllm.launch = orig_launch
            sys.argv = orig_argv
        self.assertIn("--trust-remote-code", captured["serve_cmd"])
        self.assertIn("--max-num-seqs", captured["serve_cmd"])
        self.assertIn("128", captured["serve_cmd"])

    # Bug 2: the NPU is held by the `VLLM::EngineCore` child, not the
    # `vllm serve` root, so pid matching must include descendants.
    def test_process_pids_include_engine_core_child(self):
        entries = [
            (260657, 0, "/usr/bin/python3 /usr/bin/vllm serve /m --port 8000"),
            (261306, 260657, "python3 -c resource_tracker"),
            (261307, 260657, "VLLM::EngineCore"),
            (261737, 261307, "python3 spawn_main"),
        ]
        orig = vllm._ps_entries
        vllm._ps_entries = lambda *a, **k: entries
        try:
            pids = vllm.vllm_process_pids("c")
        finally:
            vllm._ps_entries = orig
        for p in (260657, 261306, 261307, 261737):
            self.assertIn(p, pids)

    def test_physical_devices_matches_child_pid(self):
        smi = ("| NPU     Chip | Process id | Process name | Process memory(MB) "
               "| Process id in container |\n"
               "| 2       0 | 3246291 |  | 54846 | 261307 |\n")
        orig_ps, orig_run = vllm._ps_entries, vllm.run
        vllm._ps_entries = lambda *a, **k: [
            (260657, 0, "vllm serve /m --port 8000"),
            (261307, 260657, "VLLM::EngineCore"),
        ]

        def fake_run(cmd, **kw):
            return (0, smi, "")

        vllm.run = fake_run
        try:
            npus = vllm.vllm_physical_devices("c")
        finally:
            vllm._ps_entries = orig_ps
            vllm.run = orig_run
        self.assertEqual(npus, [2])



class ArgvParsingTests(unittest.TestCase):
    def test_ps_fragments_and_exact_argv_agree(self):
        exact = ["vllm", "serve", "/m", "--port", "8000",
                 "--speculative-config",
                 '{"method": "mtp", "num_speculative_tokens": 3}',
                 "--trust-remote-code"]
        opt_exact = vllm._options_from_tokens(exact)
        _, opt_ps = vllm._argv_options(
            " ".join(shlex.quote(x) for x in exact))
        opt_mangled = vllm._options_from_tokens(shlex.split(
            "vllm serve /m --port 8000 --speculative-config "
            "{method: mtp, num_speculative_tokens: 3} --trust-remote-code"))
        for opt in (opt_exact, opt_ps, opt_mangled):
            self.assertEqual(
                vllm._normalize_option_value(opt["--speculative-config"]),
                "{method:mtp,num_speculative_tokens:3}")
            self.assertTrue(opt["--trust-remote-code"])

    def test_argv_from_cmdline_shell_wrapper_preserves_json(self):
        script = ("for f in a b; do . $f; done; exec vllm serve /m --port 8000 "
                  """--speculative-config '{"method": "mtp"}'""")
        tokens = vllm._argv_from_cmdline(["/bin/bash", "-lc", script])
        opts = vllm._options_from_tokens(tokens)
        self.assertEqual(opts["--port"], "8000")
        self.assertEqual(
            vllm._normalize_option_value(opts["--speculative-config"]),
            "{method:mtp}")

    def test_argv_from_cmdline_exec_form_is_verbatim(self):
        argv = ["/usr/bin/python3", "/usr/bin/vllm", "serve", "/m",
                "--port", "8000"]
        self.assertEqual(vllm._argv_from_cmdline(argv), argv)

    def test_shell_wrapper_ignores_trailing_redirection(self):
        script = ("for f in a b; do . $f; done; exec vllm serve /m --port 8000 "
                  """--additional-config '{"enable_cpu_binding":true}' """
                  "> /tmp/serve.log 2>&1")
        tokens = vllm._argv_from_cmdline(["/bin/bash", "-lc", script])
        opts = vllm._options_from_tokens(tokens)
        self.assertEqual(
            vllm._normalize_option_value(opts["--additional-config"]),
            "{enable_cpu_binding:true}")

    def test_proc_cmdline_splits_nul(self):
        orig = vllm.run
        vllm.run = lambda cmd, **kw: (
            0, "/usr/bin/vllm\nserve\n/m\n--port\n8000\n", "")
        try:
            self.assertEqual(vllm._proc_cmdline("c", 123),
                             ["/usr/bin/vllm", "serve", "/m",
                              "--port", "8000"])
        finally:
            vllm.run = orig


if __name__ == "__main__":
    unittest.main(verbosity=2)
