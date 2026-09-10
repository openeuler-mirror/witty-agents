#!/usr/bin/env node
"use strict";

const fs = require("fs");
const path = require("path");
const readline = require("readline");
const { spawn, spawnSync } = require("child_process");

const PKG_ROOT = path.resolve(__dirname, "..");

function usage() {
  console.log(`Usage:
  nl2sql init [--dir <path>]   Interactive config (.env + datasources)
  nl2sql start [--dir <path>]  Create venv if needed and start Web

Default --dir is this package root:
  ${PKG_ROOT}
`);
}

function parseArgs(argv) {
  const args = { cmd: "", dir: PKG_ROOT };
  const rest = argv.slice(2);
  if (!rest.length) return args;
  args.cmd = rest[0];
  for (let i = 1; i < rest.length; i++) {
    if (rest[i] === "--dir" && rest[i + 1]) {
      args.dir = path.resolve(rest[++i]);
    } else if (rest[i] === "-h" || rest[i] === "--help") {
      args.cmd = "help";
    }
  }
  return args;
}

function ask(rl, question, defaultValue = "") {
  const hint = defaultValue !== "" ? ` [${defaultValue}]` : "";
  return new Promise((resolve) => {
    rl.question(`${question}${hint}: `, (answer) => {
      const v = (answer || "").trim();
      resolve(v !== "" ? v : defaultValue);
    });
  });
}

function writeEnv(dir, values) {
  const lines = [
    `NL2SQL_LLM_BASE_URL=${values.llmBase}`,
    `NL2SQL_LLM_API_KEY=${values.llmKey}`,
    `NL2SQL_LLM_MODEL=${values.llmModel}`,
    `NL2SQL_WEB_HOST=${values.webHost}`,
    `NL2SQL_WEB_PORT=${values.webPort}`,
    `NL2SQL_RAG_BASE_URL=${values.ragBase}`,
    `NL2SQL_RAG_ACCESS_KEY=${values.ragKey}`,
    "",
  ];
  const target = path.join(dir, ".env");
  fs.writeFileSync(target, lines.join("\n"), "utf8");
  return target;
}

function patchLocalEs(yamlText, { hosts, username, password }) {
  const blockRe = /(  local-es:\n)([\s\S]*?)(?=\n  [a-zA-Z0-9_-]+:|\n*$)/;
  const m = yamlText.match(blockRe);
  if (!m) {
    throw new Error("configs/datasources.yaml 中未找到 local-es 段，请手改");
  }
  let block = m[0];
  const hostLine = `      - ${hosts}`;
  if (/hosts:\n(?:\s+- .+\n)+/.test(block)) {
    block = block.replace(/hosts:\n(?:\s+- .+\n)+/, `hosts:\n${hostLine}\n`);
  } else {
    block = block.replace(/hosts:\s*\n?/, `hosts:\n${hostLine}\n`);
  }
  block = block.replace(/username:\s*".*"/, `username: ${JSON.stringify(username)}`);
  block = block.replace(/password:\s*".*"/, `password: ${JSON.stringify(password)}`);
  return yamlText.slice(0, m.index) + block + yamlText.slice(m.index + m[0].length);
}

function makePrompter() {
  // 管道/重定向：一次性读完 stdin，避免 readline 在非 TTY 下提前 close
  if (!process.stdin.isTTY) {
    const lines = fs.readFileSync(0, "utf8").split(/\r?\n/);
    let i = 0;
    return {
      async ask(question, defaultValue = "") {
        const hint = defaultValue !== "" ? ` [${defaultValue}]` : "";
        process.stdout.write(`${question}${hint}: `);
        const raw = i < lines.length ? lines[i++] : "";
        const v = String(raw || "").trim();
        const out = v !== "" ? v : defaultValue;
        process.stdout.write(`${v !== "" ? v : "(default)"}\n`);
        return out;
      },
      close() {},
    };
  }
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  return {
    ask(question, defaultValue = "") {
      return ask(rl, question, defaultValue);
    },
    close() {
      rl.close();
    },
  };
}

async function cmdInit(dir) {
  assertPackageRoot(dir);
  const prompt = makePrompter();
  try {
    console.log(`配置目录: ${dir}\n`);
    console.log("--- LLM ---");
    const llmBase = await prompt.ask("LLM Base URL", "https://api.openai.com/v1");
    const llmKey = await prompt.ask("LLM API Key", "");
    const llmModel = await prompt.ask("LLM Model", "gpt-4o-mini");

    console.log("\n--- rag-core ---");
    const ragBase = await prompt.ask("rag-core Base URL", "http://127.0.0.1:19988");
    const ragKey = await prompt.ask("rag-core Access Key", "");

    console.log("\n--- Web ---");
    const webHost = await prompt.ask("Web host", "0.0.0.0");
    const webPort = await prompt.ask("Web port", "8199");

    console.log("\n--- 数据源 Elasticsearch (local-es) ---");
    const esHost = await prompt.ask("ES hosts URL", "http://127.0.0.1:9200");
    const esUser = await prompt.ask("ES username (可空)", "");
    const esPass = esUser ? await prompt.ask("ES password", "") : "";

    const envPath = path.join(dir, ".env");
    if (fs.existsSync(envPath)) {
      const overwrite = await prompt.ask(".env 已存在，覆盖? (y/N)", "N");
      if (!/^y(es)?$/i.test(overwrite)) {
        console.log("已跳过写入 .env");
      } else {
        writeEnv(dir, { llmBase, llmKey, llmModel, ragBase, ragKey, webHost, webPort });
        console.log(`已写入 ${envPath}`);
      }
    } else {
      writeEnv(dir, { llmBase, llmKey, llmModel, ragBase, ragKey, webHost, webPort });
      console.log(`已写入 ${envPath}`);
    }

    const dsPath = path.join(dir, "configs", "datasources.yaml");
    const yaml = fs.readFileSync(dsPath, "utf8");
    const next = patchLocalEs(yaml, { hosts: esHost, username: esUser, password: esPass });
    fs.writeFileSync(dsPath, next, "utf8");
    console.log(`已更新 ${dsPath} 中 local-es 连接`);

    console.log(`
下一步:
  1. 确保本机 Python >= 3.10，且 rag-core / ES 已就绪
  2. 规则需自行同步到 rag（Web 规则中心或 scripts/sync_rules_to_rag.py）
  3. 运行: nl2sql start${dir === PKG_ROOT ? "" : ` --dir ${dir}`}
  4. 浏览器打开 http://127.0.0.1:${webPort}
`);
  } finally {
    prompt.close();
  }
}

function assertPackageRoot(dir) {
  const need = ["requirements.txt", "apps/web/main.py", "nl2sql_core"];
  for (const rel of need) {
    const p = path.join(dir, rel);
    if (!fs.existsSync(p)) {
      throw new Error(`目录不像 NL2SQL 包根（缺少 ${rel}）: ${dir}`);
    }
  }
}

function findPython(dir) {
  const candidates = process.platform === "win32" ? ["python", "python3"] : ["python3", "python"];
  for (const bin of candidates) {
    const r = spawnSync(bin, ["-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"], {
      encoding: "utf8",
    });
    if (r.status !== 0) continue;
    const ver = (r.stdout || "").trim();
    const [maj, min] = ver.split(".").map(Number);
    if (maj > 3 || (maj === 3 && min >= 10)) {
      return { bin, ver };
    }
    console.error(`找到 ${bin} ${ver}，需要 >= 3.10`);
  }
  return null;
}

function loadDotEnv(dir) {
  const p = path.join(dir, ".env");
  const env = { ...process.env };
  if (!fs.existsSync(p)) return env;
  for (const line of fs.readFileSync(p, "utf8").split(/\r?\n/)) {
    const s = line.trim();
    if (!s || s.startsWith("#")) continue;
    const i = s.indexOf("=");
    if (i <= 0) continue;
    const k = s.slice(0, i).trim();
    let v = s.slice(i + 1).trim();
    if ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'"))) {
      v = v.slice(1, -1);
    }
    env[k] = v;
  }
  return env;
}

function venvPython(dir) {
  if (process.platform === "win32") {
    return path.join(dir, ".venv", "Scripts", "python.exe");
  }
  return path.join(dir, ".venv", "bin", "python");
}

function cmdStart(dir) {
  assertPackageRoot(dir);
  const py = findPython(dir);
  if (!py) {
    throw new Error("未找到 Python >= 3.10，请先安装后再 nl2sql start");
  }
  console.log(`使用 ${py.bin} (${py.ver})`);

  const vpy = venvPython(dir);
  const venvDir = path.join(dir, ".venv");
  if (!fs.existsSync(vpy)) {
    console.log("创建虚拟环境 .venv …");
    const r = spawnSync(py.bin, ["-m", "venv", venvDir], { cwd: dir, stdio: "inherit" });
    if (r.status !== 0) throw new Error("python -m venv 失败");
  }

  console.log("安装/更新 Python 依赖（requirements.txt）…");
  const pip = spawnSync(vpy, ["-m", "pip", "install", "-r", "requirements.txt"], {
    cwd: dir,
    stdio: "inherit",
  });
  if (pip.status !== 0) throw new Error("pip install 失败");

  const env = loadDotEnv(dir);
  if (!fs.existsSync(path.join(dir, ".env"))) {
    console.warn("警告: 未找到 .env，建议先运行 nl2sql init");
    const example = path.join(dir, ".env.example");
    if (fs.existsSync(example)) {
      fs.copyFileSync(example, path.join(dir, ".env"));
      console.warn("已从 .env.example 复制一份空模板，请尽快填写 Key");
      Object.assign(env, loadDotEnv(dir));
    }
  }

  const host = env.NL2SQL_WEB_HOST || "0.0.0.0";
  const port = env.NL2SQL_WEB_PORT || "8199";
  console.log(`启动 Web: http://127.0.0.1:${port}  (bind ${host}:${port})`);
  console.log(`健康检查: curl -s 'http://127.0.0.1:${port}/api/health'`);

  const child = spawn(
    vpy,
    ["-m", "uvicorn", "apps.web.main:app", "--host", host, "--port", String(port)],
    {
      cwd: dir,
      env: { ...env, PYTHONPATH: dir + (env.PYTHONPATH ? path.delimiter + env.PYTHONPATH : "") },
      stdio: "inherit",
    }
  );
  child.on("exit", (code) => process.exit(code == null ? 1 : code));
}

async function main() {
  const args = parseArgs(process.argv);
  if (!args.cmd || args.cmd === "help" || args.cmd === "-h") {
    usage();
    process.exit(args.cmd ? 0 : 1);
  }
  try {
    if (args.cmd === "init") {
      await cmdInit(args.dir);
    } else if (args.cmd === "start") {
      cmdStart(args.dir);
    } else {
      console.error(`未知命令: ${args.cmd}\n`);
      usage();
      process.exit(1);
    }
  } catch (e) {
    console.error(e.message || e);
    process.exit(1);
  }
}

main();
