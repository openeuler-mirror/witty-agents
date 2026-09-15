// NL2SQL Agent — OpenCode plugin entry.
// Registers `config.agent.nl2sql` (mode "primary") so OpenCode senses the agent and its skills,
// mirroring the shennong-crash-agent plugin registration mechanism.

const NL2SQL_DESCRIPTION =
  "NL2SQL Agent — 把自然语言数据需求转为对 Elasticsearch 的只读查询并返回结果";

const NL2SQL_FALLBACK_PROMPT = `你是 nl2sql Agent。把用户的自然语言数据需求转为只读查询并返回结果。

工作方式：
1. **禁止**启动或调用本机 NL2SQL Web（任何 :8199 HTTP）。
2. 用 skill 目录脚本执行/查 schema/规则：
   \`python3 <SKILL>/scripts/nl2sql_skill_cli.py <命令> ...\`
   输出为 JSON；按 JSON 回答用户。
3. 问句过糊时优先在对话里澄清。
4. 默认只读；不要编造未在返回 JSON 或规则中出现的字段/数据。`;

const NL2SQL_SKILLS = ["nl2sql"];

const NL2SQL_PERMISSION = {
  edit: "deny",
  bash: "allow",
  webfetch: "allow",
};

async function getNl2sqlPrompt() {
  try {
    const { readFileSync } = await import("node:fs");
    const { fileURLToPath } = await import("node:url");
    const { dirname, join } = await import("node:path");
    const promptFile = join(
      dirname(fileURLToPath(import.meta.url)),
      "..",
      "opencode_plugin",
      "role-prompt.md",
    );
    const prompt = readFileSync(promptFile, "utf8");
    if (prompt && prompt.trim().length > 100) return prompt;
  } catch (_e) {
    // keep embedded fallback when role-prompt.md is unavailable
  }
  return NL2SQL_FALLBACK_PROMPT;
}

const Nl2sqlAgentPlugin = async (_ctx) => {
  const prompt = await getNl2sqlPrompt();
  return {
    config: async (config) => {
      config.agent = {
        ...config.agent,
        nl2sql: {
          mode: "primary",
          prompt,
          description: NL2SQL_DESCRIPTION,
          skills: NL2SQL_SKILLS,
          permission: NL2SQL_PERMISSION,
          temperature: 0.1,
        },
      };
    },
    event: async (input) => {
      const eventName = input.event?.type ?? "unknown";
      if (process.env.NL2SQL_DEBUG) {
        console.log(`[Nl2sqlAgent] event: ${eventName}`);
      }
    },
  };
};

export default Nl2sqlAgentPlugin;