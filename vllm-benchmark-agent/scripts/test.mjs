import { execFileSync } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { packageRoot, python } from '../lib/runtime.mjs';
const sandbox = mkdtempSync(join(tmpdir(), 'vllm-tests-'));
try {
  execFileSync(process.execPath, ["--test", "tests/test-witty-integration.mjs"], {cwd: packageRoot, stdio: "inherit"});
  execFileSync(python, ['-m', 'unittest', 'discover', '-s', 'tests', '-v'], {
    cwd: packageRoot, stdio: 'inherit', env: {...process.env, HOME: sandbox,
      VLLM_BENCHMARK_DATA_DIR: join(sandbox, 'data'), PYTHONDONTWRITEBYTECODE: '1', MPLCONFIGDIR: join(sandbox, 'matplotlib')},
  });
} finally { rmSync(sandbox, {recursive: true, force: true}); }
