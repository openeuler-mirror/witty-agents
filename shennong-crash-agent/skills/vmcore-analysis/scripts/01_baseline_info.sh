#!/usr/bin/env bash
# =============================================================================
# 脚本：01_baseline_info.sh
# 用途：VMcore 基础信息收集、快速定性，并检测源码目录以决定分析路径
# 使用：bash 01_baseline_info.sh <vmcore_path> <vmlinux_path> [src_dir]
# 参数：
#   $1  vmcore 路径（默认 /var/crash/vmcore）
#   $2  vmlinux 路径（默认系统路径）
#   $3  源码目录（可选，若提供且存在则输出源码分析指引）
# =============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "${SCRIPT_DIR}/common.sh"

VMCORE="${1:-/var/crash/vmcore}"
VMLINUX_DEFAULT="/usr/lib/debug/lib/modules/$(uname -r)/vmlinux"
VMLINUX_INPUT="${2:-$VMLINUX_DEFAULT}"
VMLINUX="$(detect_vmlinux "$VMCORE" "$VMLINUX_INPUT")"
SRC_DIR="${3:-}"

DMESG_PATH="$(detect_vmcore_dmesg "$VMCORE")"

if [[ "${1:-}" == "--help" ]] || [[ "${1:-}" == "-h" ]]; then
  echo "用途：VMcore 基础信息收集与快速定性（所有分析的第一步）"
  echo "使用：bash $0 <vmcore> <vmlinux> [src_dir]"
  echo ""
  echo "  若未提供 vmlinux，脚本会尝试："
  echo "    1. 在 vmcore 同级目录查找 vmlinux"
  echo "    2. 根据 vmcore 目录名中的内核版本查找系统调试目录"
  echo "    3. 若仍未找到，则尝试使用 vmcore-dmesg.txt 进行日志级关键字匹配"
  echo ""
  echo "  src_dir: 可选，内核/驱动源码根目录"
  echo "           若提供，输出将包含源码路径的分析建议"
  echo ""
  echo "输出内容："
  echo "  - 内核版本、架构"
  echo "  - panic 类型（22类关键字匹配，含 bt 层比特翻转关键字）"
  echo "  - 调用栈 + 寄存器"
  echo "  - 分支决策推荐"
  echo "  - 分析路径推荐（源码主导 / 纯vmcore）"
  exit 0
fi

OUT_DIR="/tmp/vmcore_analysis_$(date +%Y%m%d%H%M%S)"
mkdir -p "${OUT_DIR}"

print_env_status "$VMCORE" "$VMLINUX" "$DMESG_PATH"

# 若缺少 vmlinux 且存在 dmesg，进入回退模式
FALLBACK_MODE=false
if [[ ! -f "$VMLINUX" || ! -s "$VMLINUX" ]]; then
  print_vmlinux_missing_guide "$VMCORE"
  if [[ -n "$DMESG_PATH" && -f "$DMESG_PATH" ]]; then
    FALLBACK_MODE=true
    echo "⚠️  将使用 vmcore-dmesg.txt 进行回退分析：$DMESG_PATH"
  else
    echo "❌ 错误：既找不到 vmlinux，也找不到 vmcore-dmesg.txt，无法继续分析。"
    exit 1
  fi
fi

echo "并行收集临时目录: ${OUT_DIR}"

CRASH_TIMEOUT_COMMON="${CRASH_TIMEOUT_COMMON:-600s}"
CRASH_TIMEOUT_LOG="${CRASH_TIMEOUT_LOG:-900s}"
CRASH_TIMEOUT_BT_A="${CRASH_TIMEOUT_BT_A:-900s}"
CRASH_TIMEOUT_DIS="${CRASH_TIMEOUT_DIS:-180s}"

# 封装 crash 命令执行，改为后台并行执行并输出到文件
# 参数1: crash内部命令, 参数2: 输出文件名, 参数3: 描述信息
run_crash_async() {
  local cmd="$1"
  local out_file="${OUT_DIR}/$2"
  local raw_file="${out_file}.raw"
  local err_file="${out_file}.err"
  local desc="$3"
  local timeout_s="${4:-${CRASH_TIMEOUT_COMMON}}"
  echo "正在收集: ${desc} ..."
  (
    if ! command -v crash >/dev/null 2>&1; then
      echo "crash 命令不存在（PATH: ${PATH}）" > "${err_file}"
      : > "${out_file}"
      echo "  [失败] ${desc} -> ${out_file} (stderr: ${err_file})" >> "${OUT_DIR}/summary.txt"
      exit 0
    fi

    set +e
    printf '%s\nquit\n' "$cmd" | timeout "${timeout_s}" crash -s "${VMLINUX}" "${VMCORE}" > "${raw_file}" 2>"${err_file}"
    local crash_rc=$?
    set -e

    grep -v "^WARNING: active task" "${raw_file}" > "${out_file}" || true

    if [[ $crash_rc -eq 0 ]]; then
      rm -f "${raw_file}" "${err_file}" || true
      echo "  [成功] ${desc} -> ${out_file}" >> "${OUT_DIR}/summary.txt"
    else
      echo "  [失败/超时 rc=${crash_rc}] ${desc} -> ${out_file} (stderr: ${err_file})" >> "${OUT_DIR}/summary.txt"
    fi
  ) &
}

run_crash_sync() {
  local cmd="$1"
  local out_file="${OUT_DIR}/$2"
  local raw_file="${out_file}.raw"
  local err_file="${out_file}.err"
  local desc="$3"
  local timeout_s="$4"

  echo "正在收集: ${desc} ..."
  if ! command -v crash >/dev/null 2>&1; then
    echo "crash 命令不存在（PATH: ${PATH}）" > "${err_file}"
    : > "${out_file}"
    echo "  [失败] ${desc} -> ${out_file} (stderr: ${err_file})" >> "${OUT_DIR}/summary.txt"
    return 0
  fi

  set +e
  printf '%s\nquit\n' "$cmd" | timeout "${timeout_s}" crash -s "${VMLINUX}" "${VMCORE}" > "${raw_file}" 2>"${err_file}"
  local crash_rc=$?
  set -e

  grep -v "^WARNING: active task" "${raw_file}" > "${out_file}" || true

  if [[ $crash_rc -eq 0 ]]; then
    rm -f "${raw_file}" "${err_file}" || true
    echo "  [成功] ${desc} -> ${out_file}" >> "${OUT_DIR}/summary.txt"
  else
    echo "  [失败/超时 rc=${crash_rc}] ${desc} -> ${out_file} (stderr: ${err_file})" >> "${OUT_DIR}/summary.txt"
  fi
}

# 检测源码目录
HAS_SRC=false
SRC_STATUS="未提供（将使用纯vmcore分析路径）"
if [[ -n "${SRC_DIR}" && -d "${SRC_DIR}" ]]; then
  HAS_SRC=true
  SRC_COUNT=$(find "${SRC_DIR}" -name "*.c" 2>/dev/null | wc -l)
  SRC_STATUS="已找到：${SRC_DIR}（包含 ${SRC_COUNT} 个 .c 文件）→ 将使用源码主导分析路径"
fi

echo "==================================================================" > "${OUT_DIR}/summary.txt"
echo " VMcore 基础信息收集汇总报告" >> "${OUT_DIR}/summary.txt"
echo " 生成时间：$(date)" >> "${OUT_DIR}/summary.txt"
echo " vmcore  ：${VMCORE}" >> "${OUT_DIR}/summary.txt"
echo " vmlinux ：${VMLINUX}" >> "${OUT_DIR}/summary.txt"
if $FALLBACK_MODE; then
  echo " 分析模式：回退模式（仅使用 vmcore-dmesg.txt，缺少 vmlinux）" >> "${OUT_DIR}/summary.txt"
else
  echo " 分析模式：完整模式（crash + vmlinux）" >> "${OUT_DIR}/summary.txt"
fi
echo " 源码目录：${SRC_STATUS}" >> "${OUT_DIR}/summary.txt"
echo " 超时设置：common=${CRASH_TIMEOUT_COMMON}, log=${CRASH_TIMEOUT_LOG}, bt-a=${CRASH_TIMEOUT_BT_A}, dis=${CRASH_TIMEOUT_DIS}" >> "${OUT_DIR}/summary.txt"
echo " 结果目录：${OUT_DIR}" >> "${OUT_DIR}/summary.txt"
echo "==================================================================" >> "${OUT_DIR}/summary.txt"
echo "" >> "${OUT_DIR}/summary.txt"
echo "【执行状态概览】" >> "${OUT_DIR}/summary.txt"

echo ""
if $FALLBACK_MODE; then
  echo "进入回退模式：仅使用 vmcore-dmesg.txt 进行日志关键字匹配..."
  cp -f "${DMESG_PATH}" "${OUT_DIR}/log.txt"
  echo "  [成功] 内核日志 (log) -> ${OUT_DIR}/log.txt (来自 vmcore-dmesg.txt)" >> "${OUT_DIR}/summary.txt"
else
  echo "正在并行收集各项信息，请耐心等待..."
  echo "------------------------------------------------------------------"

  run_crash_async 'sys'    "sys.txt"    "系统基础信息 (sys)" "${CRASH_TIMEOUT_COMMON}"
  run_crash_async 'log'    "log.txt"    "内核日志 (log)" "${CRASH_TIMEOUT_LOG}"
  run_crash_async 'bt'     "bt.txt"     "当前崩溃调用栈 (bt)" "${CRASH_TIMEOUT_COMMON}"
  run_crash_async 'bt -l'  "bt_l.txt"  "带行号调用栈 (bt -l)" "${CRASH_TIMEOUT_COMMON}"
  run_crash_async 'bt -a'  "bt_a.txt"  "所有CPU调用栈 (bt -a)" "${CRASH_TIMEOUT_BT_A}"
  run_crash_async 'bt -f'  "bt_f.txt"  "调用栈与寄存器 (bt -f)" "${CRASH_TIMEOUT_COMMON}"
  run_crash_async 'mod'    "mod.txt"    "已加载内核模块 (mod)" "${CRASH_TIMEOUT_COMMON}"
  run_crash_async 'kmem -i' "kmem_i.txt" "内存状态概览 (kmem -i)" "${CRASH_TIMEOUT_COMMON}"
  run_crash_async 'ps'     "ps.txt"     "进程状态概览 (ps)" "${CRASH_TIMEOUT_COMMON}"

  wait

  # --------------------------------------------------------------------------
  # 崩溃地址反汇编（依赖 bt 结果，wait 后执行）
  # --------------------------------------------------------------------------
  RIP_FUNC=$(grep -m 1 -E '^ *#0' "${OUT_DIR}/bt.txt" 2>/dev/null | awk '{print $NF}' || true)
  if [[ -n "$RIP_FUNC" ]]; then
    run_crash_sync "dis -l ${RIP_FUNC}" "dis_l.txt" "崩溃地址反汇编 (dis -l ${RIP_FUNC})" "${CRASH_TIMEOUT_DIS}"
  else
    echo "  [跳过] 崩溃地址反汇编 (dis) -> 未提取到 RIP_FUNC" >> "${OUT_DIR}/summary.txt"
  fi
fi

echo ""
echo "信息收集完成，所有结果已保存在: ${OUT_DIR}"
echo "------------------------------------------------------------------"

echo "" >> "${OUT_DIR}/summary.txt"
echo "【核心内容摘要】" >> "${OUT_DIR}/summary.txt"
echo "------------------------------------------------------------------" >> "${OUT_DIR}/summary.txt"

# --------------------------------------------------------------------------
# 关键字匹配（22类故障模式 + Bit Flip + 手动触发）
# 匹配来源：
#   - 完整模式：log.txt（内核日志）由 crash 生成
#   - 回退模式：log.txt 为 vmcore-dmesg.txt 的副本
# --------------------------------------------------------------------------
echo "1. 故障类型关键字匹配结果：" >> "${OUT_DIR}/summary.txt"

MATCHED=()
while IFS= read -r line; do
  [[ -n "$line" ]] && MATCHED+=("$line")
done < <(match_branches_from_log "${OUT_DIR}/log.txt")

for match in "${MATCHED[@]}"; do
  echo "  ✓ MATCHED: ${match}" >> "${OUT_DIR}/summary.txt"
done

if [ ${#MATCHED[@]} -eq 0 ]; then
  echo "  ✗ 无明确故障类型关键字，需通过调用栈进一步判断" >> "${OUT_DIR}/summary.txt"
fi

# --------------------------------------------------------------------------
# D 状态进程
# --------------------------------------------------------------------------
echo "" >> "${OUT_DIR}/summary.txt"
if $FALLBACK_MODE; then
  echo "2. D 状态进程（回退模式跳过，需要 vmlinux 才能获取）：" >> "${OUT_DIR}/summary.txt"
else
  echo "2. D 状态进程（可能与崩溃相关）Top 20：" >> "${OUT_DIR}/summary.txt"
  grep " D " "${OUT_DIR}/ps.txt" 2>/dev/null | head -20 >> "${OUT_DIR}/summary.txt" || true
fi

# --------------------------------------------------------------------------
# 综合决策输出
# --------------------------------------------------------------------------
echo "" >> "${OUT_DIR}/summary.txt"
echo "==================================================================" >> "${OUT_DIR}/summary.txt"
echo " 后续分析脚本指引" >> "${OUT_DIR}/summary.txt"
echo "==================================================================" >> "${OUT_DIR}/summary.txt"

if $FALLBACK_MODE; then
  echo "当前为回退模式，已根据 vmcore-dmesg.txt 完成关键字匹配。" >> "${OUT_DIR}/summary.txt"
  echo "如需完整分析，请提供对应版本的 vmlinux 后重新执行。" >> "${OUT_DIR}/summary.txt"
fi

if [ ${#MATCHED[@]} -gt 0 ]; then
  for b in "${MATCHED[@]}"; do
    SCRIPT=$(echo "$b" | grep -oP 'scripts/\S+')
    if [[ -n "$SCRIPT" ]]; then
      if $HAS_SRC; then
        echo "建议执行: bash ${SCRIPT} ${VMCORE} ${VMLINUX} ${SRC_DIR}" >> "${OUT_DIR}/summary.txt"
      else
        echo "建议执行: bash ${SCRIPT} ${VMCORE} ${VMLINUX}" >> "${OUT_DIR}/summary.txt"
      fi
      if $FALLBACK_MODE; then
        echo "         （注意：分支脚本需要有效的 vmlinux 才能运行）" >> "${OUT_DIR}/summary.txt"
      fi
    fi
  done
else
  echo "未匹配到特定故障分支，需根据调用栈进行进一步分析。" >> "${OUT_DIR}/summary.txt"
fi
echo "==================================================================" >> "${OUT_DIR}/summary.txt"

# 最终输出
cat "${OUT_DIR}/summary.txt"
