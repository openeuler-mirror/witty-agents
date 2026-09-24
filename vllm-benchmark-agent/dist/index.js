import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
const root = dirname(dirname(fileURLToPath(import.meta.url)));
// Use the installed entry directly, so project-local npm installs need no PATH changes.
const cli = [process.execPath, join(root, 'bin', 'vllm-benchmark.mjs')]
  .map(value => "'" + value.replaceAll("'", "'\\''") + "'").join(' ');
const prompt = name => readFileSync(join(root, 'agent', name), 'utf8')
  .replaceAll('vllm-benchmark ', `${cli} `);
export default async () => ({
  config: async config => {
    config.agent = {
      ...config.agent,
      'vllm-benchmark': {
        mode: 'primary', description: 'Ascend vLLM 自动压测与性能分析',
        prompt: prompt('agent.md'), skills: ['vllm-benchmark'], temperature: 0.1,
        permission: {edit: 'deny', bash: {'*': 'ask', [`${cli} *`]: 'allow'}},
      },
      'benchmark-config': {
        mode: 'all', description: '编辑并校验 benchmark.yaml',
        prompt: prompt('benchmark-config.md'),
        permission: {edit: 'allow', bash: {'*': 'ask', [`${cli} config*`]: 'allow', [`${cli} status*`]: 'allow'}},
      },
    };
    config.command = {...config.command, benchmark_config: {
      description: '编辑并校验 benchmark.yaml', agent: 'benchmark-config',
      template: '根据用户要求修改工作目录中的 benchmark.yaml，并执行配置校验；不启动压测。用户输入：$ARGUMENTS',
    }};
  },
});
