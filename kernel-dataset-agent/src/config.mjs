// 配置解析，优先级由低到高：
//   内置默认值 <- 包内示例 config/datasets.json <- 用户配置 <- 环境变量 <- 命令行覆盖
// 数据根目录（dataRoot）不做任何假设：默认 /home/data，可通过用户配置、KERNEL_DATASET_ROOT
// 或 --root 指向任意路径，便于在其他机器上复用；其下的目录结构与字段格式与既有数据完全一致。
import { existsSync, readFileSync } from "node:fs"
import { homedir } from "node:os"
import { dirname, isAbsolute, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"

export const PACKAGE_ROOT = resolve(dirname(fileURLToPath(import.meta.url)), "..")
export const RUNTIME_DIR = join(PACKAGE_ROOT, ".runtime")
export const STATE_DIR = join(RUNTIME_DIR, "state")
// 包内示例配置：只作为默认值随包分发，升级会被覆盖，不建议在此写机器专属路径。
export const PACKAGE_CONFIG_FILE = join(PACKAGE_ROOT, "config", "datasets.json")
// 用户配置（每台机器一份，升级不丢）：$KERNEL_DATASET_CONFIG > $XDG_CONFIG_HOME/kernel-dataset-agent/datasets.json > ~/.config/...
export function userConfigFile(env = process.env) {
  if (env.KERNEL_DATASET_CONFIG) return resolve(env.KERNEL_DATASET_CONFIG)
  const configHome = env.XDG_CONFIG_HOME ? resolve(env.XDG_CONFIG_HOME) : join(homedir(), ".config")
  return join(configHome, "kernel-dataset-agent", "datasets.json")
}

// 内置默认数据根目录（可被后续任一层覆盖）
export const DEFAULT_DATA_ROOT = "/home/data"

// 数据集定义：dir/filePrefix/上游接口/水位字段，与本地既有文件一一对应。
const DEFAULT_DATASETS = {
  "linux-bugzilla": {
    enabled: true,
    kind: "bugzilla-rest",
    dir: "linux/bugzilla",
    filePrefix: "bugzilla_",
    bugzillaUrl: "https://bugzilla.kernel.org",
    idField: "id",
    watermarkField: "last_change_time",
    initialSince: null,
  },
  "linux-commit": {
    enabled: true,
    kind: "github-commits",
    dir: "linux/commit",
    filePrefix: "commit_",
    repo: "torvalds/linux",
    idField: "sha",
    watermarkPath: "commit.committer.date",
    initialSince: null,
  },
  "linux-email": {
    enabled: true,
    kind: "lkml-mhonarc",
    dir: "linux/email",
    archiveUrl: "https://lkml.iu.edu/hypermail/linux/kernel",
    monthsBack: 2,
    activeBatch: null,
    maxBatchFiles: 700000,
    maxBatchBytes: 12884901888,
  },
  "openeuler-commit": {
    enabled: true,
    kind: "gitcode-commits",
    dir: "openEuler/commit",
    filePrefix: "commit_",
    repo: "openeuler/kernel",
    idField: "sha",
    watermarkPath: "commit.committer.date",
    initialSince: null,
  },
  "openeuler-issue": {
    enabled: true,
    kind: "gitcode-issues",
    dir: "openEuler/issue",
    filePrefix: "issue_",
    repo: "openeuler/kernel",
    idField: "number",
    watermarkPath: "updated_at",
    initialSince: null,
  },
}

export const DEFAULT_CONFIG = {
  dataRoot: DEFAULT_DATA_ROOT,
  intervalMs: 3600000,
  request: {
    timeoutMs: 30000,
    retries: 3,
    backoffMs: 1000,
    pageSize: 100,
  },
  backfill: {
    enabled: true,
  },
  tokens: {
    github: "",
    gitcode: "",
  },
  datasets: DEFAULT_DATASETS,
}

function isPlainObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value)
}

function deepMerge(base, override) {
  if (!isPlainObject(override)) return base
  const merged = { ...base }
  for (const [key, value] of Object.entries(override)) {
    merged[key] = isPlainObject(value) && isPlainObject(base[key])
      ? deepMerge(base[key], value)
      : value
  }
  return merged
}

function parseBoolean(value) {
  return ["1", "true", "yes", "on"].includes(String(value).trim().toLowerCase())
}

function parseDatasetFilter(value) {
  return String(value || "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean)
}

function readConfigFile(file) {
  if (!existsSync(file)) return {}
  try {
    return JSON.parse(readFileSync(file, "utf8"))
  } catch (error) {
    throw new Error(`配置文件解析失败 ${file}: ${error.message}`)
  }
}

function applyEnvironment(config, env) {
  const next = { ...config }
  if (env.KERNEL_DATASET_ROOT) next.dataRoot = env.KERNEL_DATASET_ROOT
  if (env.KERNEL_DATASET_INTERVAL_MS) next.intervalMs = Number(env.KERNEL_DATASET_INTERVAL_MS)
  next.tokens = {
    github: env.KERNEL_DATASET_TOKEN_GITHUB || env.GITHUB_TOKEN || config.tokens.github,
    gitcode: env.KERNEL_DATASET_TOKEN_GITCODE || env.GITCODE_TOKEN || config.tokens.gitcode,
  }
  if (env.KERNEL_DATASET_PAGE_SIZE) next.request = { ...next.request, pageSize: Number(env.KERNEL_DATASET_PAGE_SIZE) }

  const enabled = parseDatasetFilter(env.KERNEL_DATASET_DATASETS)
  const disabled = parseDatasetFilter(env.KERNEL_DATASET_DISABLE)
  const datasets = {}
  for (const [id, definition] of Object.entries(next.datasets)) {
    let isEnabled = definition.enabled !== false
    if (enabled.length > 0) isEnabled = enabled.includes(id)
    if (disabled.includes(id)) isEnabled = false
    const initialSince = env[`KERNEL_DATASET_INITIAL_SINCE_${id.toUpperCase().replace(/-/g, "_")}`]
      || definition.initialSince
      || null
    datasets[id] = { ...definition, enabled: isEnabled, initialSince }
  }
  next.datasets = datasets
  if (!Number.isFinite(next.intervalMs) || next.intervalMs < 60000) {
    throw new Error(`KERNEL_DATASET_INTERVAL_MS 无效（需 >= 60000 毫秒）: ${env.KERNEL_DATASET_INTERVAL_MS}`)
  }
  return next
}

export function loadConfig({ env = process.env, configFile = null, overrides = {} } = {}) {
  const packageConfig = readConfigFile(PACKAGE_CONFIG_FILE)
  const userFile = configFile || userConfigFile(env)
  const userConfig = readConfigFile(userFile)

  let config = deepMerge(DEFAULT_CONFIG, packageConfig)
  config = deepMerge(config, userConfig)
  config = applyEnvironment(config, env)
  if (overrides.dataRoot) config.dataRoot = overrides.dataRoot
  if (overrides.intervalMs) config.intervalMs = overrides.intervalMs
  config.dataRoot = isAbsolute(config.dataRoot) ? config.dataRoot : resolve(PACKAGE_ROOT, config.dataRoot)
  // 供 check 输出与排障使用：当前生效的配置来源
  config.configFiles = [PACKAGE_CONFIG_FILE, userFile].filter((file) => existsSync(file))
  config.dataRootSource = dataRootSource({ env, overrides, packageConfig, userConfig })
  return config
}

function dataRootSource({ env, overrides, packageConfig, userConfig }) {
  if (overrides.dataRoot) return "cli"
  if (env.KERNEL_DATASET_ROOT) return "env"
  if (userConfig.dataRoot) return "user-config"
  if (packageConfig.dataRoot) return "package-config"
  return "default"
}

export function datasetDir(config, dataset) {
  return join(config.dataRoot, dataset.dir)
}

export function datasetPath(config, dataset, id) {
  return join(datasetDir(config, dataset), `${dataset.filePrefix}${id}.json`)
}

export function datasetStateFile(datasetId) {
  return join(STATE_DIR, `${datasetId}.json`)
}

export function datasetConfig(config, datasetId) {
  const dataset = config.datasets[datasetId]
  if (!dataset) throw new Error(`未知数据集: ${datasetId}`)
  return dataset
}