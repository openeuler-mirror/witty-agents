#!/bin/bash
set -euo pipefail
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
log_info()  { echo -e "${GREEN}[INFO]${NC} $*"; }
log_warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
log_err()  { echo -e "${RED}[ERR]${NC}  $*"; }

SKILLS_DIR="${SKILLS_DIR:-$HOME/.config/opencode/skills}"
SKILLHUB_URL="https://skillhub-1388575217.cos.ap-guangzhou.myqcloud.com/install/install.sh"

echo ""
echo "====================================="
echo "  openEuler Ops Agent Installer"
echo "====================================="
echo ""

# --- skillhub CLI ---
find_skillhub() {
  # 搜索所有可能路径
  for candidate in \
    "$HOME/.local/bin/skillhub" \
    "/usr/local/bin/skillhub" \
    "/usr/bin/skillhub"; do
    [ -x "$candidate" ] && echo "$candidate" && return 0
  done
  command -v skillhub 2>/dev/null && return 0
  return 1
}

install_skillhub() {
  log_info "Step 1: 安装 skillhub CLI..."
  curl -fsSL "$SKILLHUB_URL" | bash || {
    log_err "skillhub 自动安装失败，请手动安装: curl -fsSL $SKILLHUB_URL | bash"
    return 1
  }
  # 重新搜索安装后的位置
  SKHUB="$(find_skillhub)" || {
    log_err "skillhub 安装后仍找不到，请检查 ~/.local/bin 是否在 PATH"
    log_err "临时添加: export PATH=\"\$HOME/.local/bin:\$PATH\""
    return 1
  }
  log_info "skillhub CLI 安装完成 ✓"
  return 0
}

log_info "Step 1: 检查 skillhub CLI..."
if SKHUB="$(find_skillhub)"; then
  log_info "skillhub CLI 已存在: $SKHUB ✓"
elif install_skillhub; then
  : # SKHUB 已在 install_skillhub 中设置
else
  log_err "无法安装 skillhub CLI，跳过 Skill 安装步骤"
  SKHUB=""
fi

mkdir -p "$SKILLS_DIR"

# --- experience-skill (知识库) ---
EXPERIENCE_SKILL_BASE="/usr/share/witty/opencode/skills/experience_skill"
EXPERIENCE_SKILL_SCRIPTS="$EXPERIENCE_SKILL_BASE/scripts"

if [ -f "$EXPERIENCE_SKILL_SCRIPTS/pyproject.toml" ]; then
  log_info "Step 2: experience-skill 已存在，初始化..."
else
  log_info "Step 2: 安装 experience-skill..."
  mkdir -p "$(dirname "$EXPERIENCE_SKILL_BASE")"
  if [ ! -d "$EXPERIENCE_SKILL_BASE" ]; then
    log_warn "experience-skill 未找到，请手动安装到 $EXPERIENCE_SKILL_BASE"
    log_warn "也可以从 skillhub 安装: skillhub install experience-skill --dir $(dirname $EXPERIENCE_SKILL_BASE)"
    log_warn "暂时跳过，Agent 将使用 openEuler MCP 实时查询作为兜底"
  fi
fi

if [ -f "$EXPERIENCE_SKILL_SCRIPTS/pyproject.toml" ]; then
  cd "$EXPERIENCE_SKILL_SCRIPTS"
  if command -v uv &>/dev/null; then
    uv sync 2>&1 | sed 's/^/  /' || log_warn "uv sync 失败"
    uv run experience-skill sync 2>&1 | sed 's/^/  /' || true
    log_info "experience-skill 初始化完成 ✓"
  else
    log_warn "uv 未安装，请: pip install uv && cd $EXPERIENCE_SKILL_SCRIPTS && uv sync"
  fi
  cd - > /dev/null
fi

# --- 安装 Skills ---
declare -A SKILLS=(
  ["cool-agent-tools"]="chuangyinbot-boop"
  ["ssh-remote-sanitized"]="nickliang"
  ["ops-maintenance"]="fish1981bimmer"
  ["buddy-log-analyzer"]="user_00c9b356"
  ["system-log-analyzer"]="godyounger"
  ["kubernetes"]="kcns008"
  ["docker-diag"]="mkrdiop"
  ["self-improving-agent"]="pskoett"
  ["skill-vetter"]="spclaudehome"
  ["summarize"]="paudyyin"
)

log_info "Step 3: 安装 Skills..."
if [ -n "$SKHUB" ]; then
for skill in "${!SKILLS[@]}"; do
  ns="${SKILLS[$skill]}"
  $SKHUB install "$skill" --namespace "$ns" --dir "$SKILLS_DIR" 2>&1 | grep -E "Installed|already|error" | sed 's/^/  /' || true
done
else
  log_warn "skillhub CLI 不可用，跳过 Skill 安装"
  log_warn "请手动安装 skillhub 后重新运行: openeuler-ops-agent install"
fi

# --- Agent 配置 ---
log_info "Step 4: 注册 Agent..."

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
AGENT_MD="$SCRIPT_DIR/agent.md"

for cfg in "$HOME/.config/opencode/opencode.jsonc" "$HOME/.opencode.jsonc" "$HOME/opencode.jsonc"; do
  [ -f "$cfg" ] && OPENCODE_CONFIG="$cfg" && break
done

if [ -z "${OPENCODE_CONFIG:-}" ]; then
  log_warn "未找到 opencode 配置文件，请在 MCP 配置后手动重启 opencode"
else
  node -e "
    const fs = require('fs');
    let raw = fs.readFileSync('$OPENCODE_CONFIG','utf8');

    // JSONC parser (handles // and /* */ comments correctly, preserves URLs)
    let result='', inString=false, inComment=false;
    for(let i=0;i<raw.length;i++){
      const ch=raw[i], next=raw[i+1];
      if(inComment){ if(ch==='\n'){inComment=false;result+=ch;} continue; }
      if(inString){ result+=ch;       if(ch==='\\\\'){i++;result+=next;continue;} if(ch==='\"')inString=false; continue; }
      if(ch==='\"'){inString=true;result+=ch;continue;}
      if(ch==='/'&&next==='/'){inComment=true;i++;continue;}
      if(ch==='/'&&next==='*'){const end=raw.indexOf('*/',i+2);if(end!==-1){i=end+1;}continue;}
      result+=ch;
    }
    result=result.replace(/,(\s*[}\]])/g,'\$1');
    const cfg=JSON.parse(result);

    cfg.agent = cfg.agent || {};
    cfg.agent['openeuler-ops'] = {
      description: 'openEuler 运维助手 — 故障排查/巡检/CVE/加固/调优等16个场景',
      prompt: '{file:$AGENT_MD}',
      skills: ['agent-tools','ssh-remote-skill','ops-maintenance','log-analyzer','kubernetes','docker-diag','self-improvement','skill-vetter','summarize','buddy-log-analyzer'],
    };
    fs.writeFileSync('$OPENCODE_CONFIG', JSON.stringify(cfg, null, 2));
    console.log('  Agent 已注册到 $OPENCODE_CONFIG ✓');
  " 2>&1 | sed 's/^/  /'
fi

log_info "====================================="
log_info "  安装完成！重启 opencode 即可使用。"
log_info "  对话中直接输入运维问题，Agent 自动匹配场景。"
log_info "====================================="
echo ""
