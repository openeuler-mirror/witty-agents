import { homedir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
export const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
export const venv = resolve(process.env.VLLM_BENCHMARK_VENV || join(process.env.XDG_CACHE_HOME || join(homedir(), '.cache'), 'witty-agents', 'vllm-benchmark', 'venv'));
export const python = join(venv, 'bin', 'python');
