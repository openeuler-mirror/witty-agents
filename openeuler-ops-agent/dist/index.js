// openEuler Ops Agent — OpenCode plugin entry.
// Registers `config.agent.openeuler-ops` (mode "primary") so OpenCode senses the agent and its skills,
// mirroring the shennong-crash-agent plugin registration mechanism.

const OPENEULER_OPS_DESCRIPTION =
  "openEuler 运维助手 — 覆盖故障排查、巡检、CVE修复、安全加固、性能调优等16个场景";

const OPENEULER_OPS_FALLBACK_PROMPT = `你是 openEuler 运维 Agent，一个专门为 openEuler 操作系统设计的智能运维助手。你覆盖 16 个运维场景，通过自然语言对话帮助用户解决实际问题。

## 核心能力

你通过三层架构完成工作：
1. **知识库层** — 基于 experience-skill 检索已验证的运维知识（Wiki Hub 最优先），降低幻觉
2. **技能层** — 调用安装的原子 Skill 执行具体操作（系统命令、日志分析、远程执行等）
3. **工作流层** — 按照预定义的排查步骤推进，确保完整性和可复现性`;

const OPENEULER_OPS_SKILLS = [
  "buddy-log-analyzer",
  "cool-agent-tools",
  "docker-diag",
  "experience-skill",
  "kubernetes",
  "ops-maintenance",
  "self-improving-agent",
  "skill-vetter",
  "ssh-remote-sanitized",
  "summarize",
  "system-log-analyzer",
];

const OPENEULER_OPS_PERMISSION = {
  edit: "allow",
  bash: "allow",
  webfetch: "allow",
};

async function getOpenEulerOpsPrompt() {
  try {
    const { readFileSync } = await import("node:fs");
    const { fileURLToPath } = await import("node:url");
    const { dirname, join } = await import("node:path");
    const promptFile = join(
      dirname(fileURLToPath(import.meta.url)),
      "..",
      "agent.md",
    );
    const prompt = readFileSync(promptFile, "utf8");
    if (prompt && prompt.trim().length > 100) return prompt;
  } catch (_e) {
    // keep embedded fallback when agent.md is unavailable
  }
  return OPENEULER_OPS_FALLBACK_PROMPT;
}

const OpenEulerOpsAgentPlugin = async (_ctx) => {
  const prompt = await getOpenEulerOpsPrompt();
  return {
    config: async (config) => {
      config.agent = {
        ...config.agent,
        "openeuler-ops": {
          mode: "primary",
          prompt,
          description: OPENEULER_OPS_DESCRIPTION,
          skills: OPENEULER_OPS_SKILLS,
          permission: OPENEULER_OPS_PERMISSION,
          temperature: 0.1,
        },
      };
    },
    event: async (input) => {
      const eventName = input.event?.type ?? "unknown";
      if (process.env.OPENEULER_OPS_DEBUG) {
        console.log(`[OpenEulerOpsAgent] event: ${eventName}`);
      }
    },
  };
};

export default OpenEulerOpsAgentPlugin;