#!/bin/bash
set -euo pipefail
GREEN='\033[0;32m'; YELLOW='\033[1;33m'; NC='\033[0m'
PASS="${GREEN}✓${NC}"; WARN="${YELLOW}⚠${NC}"
SKILLS_DIR="${SKILLS_DIR:-$HOME/.config/opencode/skills}"
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

check() { if [ -e "$1" ]; then echo -e "  ${PASS} ${2}"; else echo -e "  ${WARN} ${2}"; fi; }

echo ""
echo "openEuler Ops Agent 安装验证"
echo "============================"
echo ""

echo "[Skills]"
check "$SKILLS_DIR/@chuangyinbot-boop/cool-agent-tools/SKILL.md"     "agent-tools"
check "$SKILLS_DIR/@nickliang/ssh-remote-sanitized/SKILL.md"         "ssh-remote-skill"
check "$SKILLS_DIR/@fish1981bimmer/ops-maintenance/SKILL.md"         "ops-maintenance"
check "$SKILLS_DIR/@godyounger/system-log-analyzer/SKILL.md"         "log-analyzer"
check "$SKILLS_DIR/@kcns008/kubernetes/SKILL.md"                     "kubernetes"
check "$SKILLS_DIR/@mkrdiop/docker-diag/SKILL.md"                    "docker-diag"
check "$SKILLS_DIR/@pskoett/self-improving-agent/SKILL.md"           "self-improvement"
check "$SKILLS_DIR/@spclaudehome/skill-vetter/SKILL.md"              "skill-vetter"
check "$SKILLS_DIR/@paudyyin/summarize/SKILL.md"                     "summarize"
check "$SKILLS_DIR/@user_00c9b356/buddy-log-analyzer/SKILL.md"      "buddy-log-analyzer"

echo ""
echo "[experience-skill]"
EXPERIENCE_SKILL="/usr/share/witty/opencode/skills/experience_skill/scripts/pyproject.toml"
check "$EXPERIENCE_SKILL" "experience-skill (pyproject.toml)"
if [ -f "$EXPERIENCE_SKILL" ]; then
  cd "$(dirname "$EXPERIENCE_SKILL")" 2>/dev/null && uv run experience-skill sync 2>&1 | head -1 || true
fi

echo ""
echo "[Agent]"
check "$SCRIPT_DIR/agent.md" "agent.md (prompt)"

echo ""
echo "[Config]"
for cfg in "$HOME/.config/opencode/opencode.jsonc" "$HOME/.opencode.jsonc"; do
  [ -f "$cfg" ] && check "$cfg" "opencode config" && break
done

echo ""
echo "============================"
echo -e "${GREEN}验证完成${NC}"
