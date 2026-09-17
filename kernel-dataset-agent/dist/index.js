// kernel-dataset Agent —— OpenCode 插件入口。
// 注册 config.agent["kernel-dataset"]（primary），使 OpenCode 感知该 Agent 及其 skill，
// 与 shennong-crash / xlite-perf-optimizer 的注册机制保持一致。

const KERNEL_DATASET_DESCRIPTION =
  "内核数据集增量更新 Agent — 定时从上游（bugzilla / GitHub / GitCode / LKML）拉取增量，按数据根目录（dataRoot，默认 /home/data，可配置）既有目录格式落盘";

const KERNEL_DATASET_FALLBACK_PROMPT = `你是 kernel-dataset，一名负责维护本地内核数据集（数据根目录 dataRoot，默认 /home/data，可用用户配置 / KERNEL_DATASET_ROOT / --root 指向任意路径）增量更新的运维 Agent。

你的职责是：
1. 用 kernel-dataset-setup 启动/巡检常驻采集服务，保证每 1 小时把上游增量落盘；
2. 采集范围为 linux（bugzilla / commit / email）与 openEuler（commit / issue）五个数据集；
3. 落盘格式必须与数据根目录下既有文件逐字段一致，不得改动下游依赖的字段与目录结构；
4. 出现失败时先看 .runtime/kernel-dataset.log 与数据集状态，再决定是否回补（--since / --full）；
5. 需要确认当前生效的数据根目录时，执行 kernel-dataset-setup check 看 dataRoot 与 dataRootSource。`;

const KERNEL_DATASET_SKILLS = ["kernel-dataset"];

const KERNEL_DATASET_PERMISSION = {
  edit: "allow",
  bash: "allow",
  webfetch: "allow",
};

async function getKernelDatasetPrompt() {
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
  return KERNEL_DATASET_FALLBACK_PROMPT;
}

const KernelDatasetAgentPlugin = async (_ctx) => {
  const prompt = await getKernelDatasetPrompt();
  return {
    config: async (config) => {
      config.agent = {
        ...config.agent,
        "kernel-dataset": {
          mode: "primary",
          prompt,
          description: KERNEL_DATASET_DESCRIPTION,
          skills: KERNEL_DATASET_SKILLS,
          permission: KERNEL_DATASET_PERMISSION,
          temperature: 0.1,
        },
      };
    },
    event: async (input) => {
      const eventName = input.event?.type ?? "unknown";
      if (process.env.KERNEL_DATASET_DEBUG) {
        console.log(`[KernelDatasetAgent] event: ${eventName}`);
      }
    },
  };
};

export default KernelDatasetAgentPlugin;