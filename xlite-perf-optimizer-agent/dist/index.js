// xlite Perf Optimizer Agent — OpenCode plugin entry.
// Registers `config.agent["xlite-perf-optimizer"]` (mode "primary") so OpenCode senses the agent
// and its skills, mirroring the shennong-crash-agent plugin registration mechanism.

const XLITE_DESCRIPTION =
  "xlite 性能优化专家 — 自动分析算子瓶颈、设计并实现优化、在昇腾容器内验证、生成 HTML 报告并支持原子回退";

const XLITE_FALLBACK_PROMPT = `你是 xlite-perf-optimizer，一名专注于昇腾 xlite 推理框架性能优化的专家 Agent。

你的任务是在收到用户给出的性能优化目标后，自动完成：
1. 分析 xlite 代码与 profiling 数据，识别瓶颈；
2. 基于 (input_tokens, output_tokens, batch_size) 估算单算子及端到端时间复杂度；
3. 设计并实现推理逻辑/算子层面的优化；
4. 在昇腾容器内编译并验证性能；
5. 生成 HTML 报告；
6. 根据测试结果保留有效修改或自动回退无效修改。`;

const XLITE_SKILLS = [
  "xlite-analyzer",
  "xlite-complexity-estimator",
  "xlite-operator-dev",
  "xlite-atomic-journal",
  "xlite-profiler",
  "xlite-ascend-runner",
  "xlite-gitcode-runner",
  "xlite-html-reporter",
];

const XLITE_PERMISSION = {
  edit: "allow",
  bash: "allow",
  webfetch: "allow",
};

async function getXlitePrompt() {
  try {
    const { readFileSync } = await import("node:fs");
    const { fileURLToPath } = await import("node:url");
    const { dirname, join } = await import("node:path");
    const promptFile = join(
      dirname(fileURLToPath(import.meta.url)),
      "..",
      "agent",
      "agent.md",
    );
    const prompt = readFileSync(promptFile, "utf8");
    if (prompt && prompt.trim().length > 100) return prompt;
  } catch (_e) {
    // keep embedded fallback when agent.md is unavailable
  }
  return XLITE_FALLBACK_PROMPT;
}

const XlitePerfOptimizerAgentPlugin = async (_ctx) => {
  const prompt = await getXlitePrompt();
  return {
    config: async (config) => {
      config.agent = {
        ...config.agent,
        "xlite-perf-optimizer": {
          mode: "primary",
          prompt,
          description: XLITE_DESCRIPTION,
          skills: XLITE_SKILLS,
          permission: XLITE_PERMISSION,
          temperature: 0.1,
        },
      };
    },
    event: async (input) => {
      const eventName = input.event?.type ?? "unknown";
      if (process.env.XLITE_OPS_DEBUG) {
        console.log(`[XlitePerfOptimizerAgent] event: ${eventName}`);
      }
    },
  };
};

export default XlitePerfOptimizerAgentPlugin;