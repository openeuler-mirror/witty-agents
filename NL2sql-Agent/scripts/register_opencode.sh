#!/usr/bin/env bash
# 将本仓库 Skill 链到系统 OpenCode skills 目录（方案甲）
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
SRC="$ROOT/opencode_plugin/skills"
# 常见 OpenCode skills 路径（按实际环境调整）
CANDIDATES=(
  "$HOME/.config/opencode/skills"
  "$HOME/.opencode/skills"
  "/usr/share/witty/opencode/skills"
)
TARGET=""
for c in "${CANDIDATES[@]}"; do
  if [[ -d "$(dirname "$c")" ]] || [[ -d "$c" ]]; then
    mkdir -p "$c"
    TARGET="$c"
    break
  fi
done
if [[ -z "$TARGET" ]]; then
  TARGET="$HOME/.config/opencode/skills"
  mkdir -p "$TARGET"
fi
ln -sfn "$SRC/nl2sql" "$TARGET/nl2sql-http"
echo "linked $SRC/nl2sql -> $TARGET/nl2sql-http"
echo "请确保 Web 已启动: http://127.0.0.1:8199"
echo "Agent 提示词: $ROOT/opencode_plugin/role-prompt.md"
