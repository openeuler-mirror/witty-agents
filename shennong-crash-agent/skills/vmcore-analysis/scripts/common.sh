#!/usr/bin/env bash
# =============================================================================
# 脚本：common.sh
# 用途：vmcore-analysis 公共函数库
# 说明：
#   - 由其他分析脚本 source 使用
#   - 提供 vmlinux 检测、vmcore-dmesg.txt 回退、日志输出等公共能力
# =============================================================================

set -uo pipefail

# 检测 vmlinux 是否存在；若不存在尝试自动查找
# 始终返回 0，输出检测到的路径；调用方需自行判断路径是否存在
detect_vmlinux() {
  local vmcore_path="$1"
  local vmlinux_path="$2"

  if [[ -f "$vmlinux_path" && -s "$vmlinux_path" ]]; then
    echo "$vmlinux_path"
    return 0
  fi

  # 尝试在 vmcore 同级目录查找 vmlinux
  local vmcore_dir
  vmcore_dir="$(dirname "$vmcore_path")"
  if [[ -f "$vmcore_dir/vmlinux" && -s "$vmcore_dir/vmlinux" ]]; then
    echo "$vmcore_dir/vmlinux"
    return 0
  fi

  # 尝试根据 vmcore 目录名中的内核版本查找系统调试目录
  local kernel_version
  kernel_version="$(basename "$vmcore_dir" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+-[^/]+' | head -1 || true)"
  if [[ -n "$kernel_version" ]]; then
    local sys_path="/usr/lib/debug/lib/modules/${kernel_version}/vmlinux"
    if [[ -f "$sys_path" && -s "$sys_path" ]]; then
      echo "$sys_path"
      return 0
    fi
  fi

  echo "$vmlinux_path"
  return 0
}

# 检测 vmcore-dmesg.txt 是否存在（通常与 vmcore 同级）
# 始终返回 0，输出路径或空字符串
detect_vmcore_dmesg() {
  local vmcore_path="$1"
  local vmcore_dir
  vmcore_dir="$(dirname "$vmcore_path")"
  local dmesg_path="$vmcore_dir/vmcore-dmesg.txt"
  if [[ -f "$dmesg_path" && -s "$dmesg_path" ]]; then
    echo "$dmesg_path"
  fi
  return 0
}

# 输出环境检查结果
print_env_status() {
  local vmcore_path="$1"
  local vmlinux_path="$2"
  local dmesg_path="${3:-}"

  echo "=================================================================="
  echo " VMcore 分析环境检查"
  echo "=================================================================="
  echo " vmcore  : $vmcore_path"
  if [[ -f "$vmlinux_path" && -s "$vmlinux_path" ]]; then
    echo " vmlinux : $vmlinux_path （已找到）"
  else
    echo " vmlinux : $vmlinux_path （未找到）"
  fi
  if [[ -n "$dmesg_path" && -f "$dmesg_path" ]]; then
    echo " dmesg   : $dmesg_path （已找到）"
  fi
  echo "=================================================================="
}

# 当缺少 vmlinux 时输出清晰的提示
print_vmlinux_missing_guide() {
  echo ""
  echo "⚠️  缺少 vmlinux（带调试信息的内核符号文件），无法使用 crash 工具进行完整分析。"
  echo ""
  echo "建议获取方式："
  echo "  1. 在崩溃机器上安装对应版本的 kernel-debuginfo 包："
  echo "       yum install kernel-debuginfo-$(cat /proc/version | awk '{print $3}')"
  echo "  2. 或将 vmlinux 文件放到 vmcore 同级目录："
  echo "       cp /usr/lib/debug/lib/modules/<kernel-version>/vmlinux $(dirname "$1")/"
  echo ""
  echo "当前将使用 vmcore-dmesg.txt 进行日志级关键字匹配，分析结果可能不完整。"
  echo ""
}

# 通用关键字匹配（支持从 dmesg 或 crash log 输出）
match_branches_from_log() {
  local log_file="$1"
  if [[ ! -f "$log_file" || ! -s "$log_file" ]]; then
    return 0
  fi

  # 过滤掉非崩溃相关的常见误报行（如 CPU  speculative 特性日志）
  local filtered_log
  filtered_log="$(mktemp)"
  grep -viE "Speculative Return Stack Overflow|SRBDS|SRDSS|MDS|TSX Async Abort|ITLB Multihit" "$log_file" > "$filtered_log" || true

  declare -A BRANCH_MAP
  BRANCH_MAP["NULL pointer dereference|unable to handle kernel NULL"]="分支A: 空指针解引用    → scripts/branch_A_null_ptr.sh"
  BRANCH_MAP["KASAN: slab-out-of-bounds|KASAN.*out-of-bounds"]="分支B: 内存越界OOB      → scripts/branch_B_oob.sh"
  BRANCH_MAP["KASAN: use-after-free|use-after-free"]="分支C: Use-After-Free   → scripts/branch_C_uaf.sh"
  BRANCH_MAP["stack-protector|kernel stack overflow|stack overflow:|stack guard page"]="分支D: 内核栈溢出       → scripts/branch_D_stack_overflow.sh"
  BRANCH_MAP["Machine check:|mce.*bank|MCE.*PROCESSOR"]="分支E: 硬件MCE          → scripts/branch_E_mce.sh"
  BRANCH_MAP["EDAC.*UE|uncorrectable.*error"]="分支F: 内存UE           → scripts/branch_F_memory_ue.sh"
  BRANCH_MAP["possible circular locking|LOCKDEP.*circular"]="分支G: 死锁             → scripts/branch_G_deadlock.sh"
  BRANCH_MAP["soft lockup|softlockup"]="分支H: Soft Lockup      → scripts/branch_H_soft_lockup.sh"
  BRANCH_MAP["hard LOCKUP|NMI watchdog.*LOCKUP"]="分支I: Hard Lockup      → scripts/branch_I_hard_lockup.sh"
  BRANCH_MAP["kernel BUG at|BUG.*line"]="分支J: BUG()触发        → scripts/branch_J_bug_trigger.sh"
  BRANCH_MAP["Out of memory|oom_kill|Killed process"]="分支K: OOM Killer       → scripts/branch_K_oom.sh"
  BRANCH_MAP["sleeping function called from invalid|might sleep"]="分支L: 原子上下文睡眠   → scripts/branch_L_atomic_sleep.sh"
  BRANCH_MAP["rcu_sched detected stalls|RCU stall"]="分支M: RCU Stall        → scripts/branch_M_rcu_stall.sh"
  BRANCH_MAP["EXT4-fs error|XFS.*corruption|btrfs.*corrupt"]="分支N: 文件系统崩溃     → scripts/branch_N_fs_corruption.sh"
  BRANCH_MAP["double free.*skb|kfree_skb.*double|skb.*poison"]="分支O: 网络子系统崩溃   → scripts/branch_O_network.sh"
  BRANCH_MAP["DMA mapping error|I/O timeout.*abort|blk.*abort"]="分支P: 存储IO崩溃       → scripts/branch_P_storage_io.sh"
  BRANCH_MAP["vmx_exit|kvm_.*exit|VMX.*exit reason"]="分支Q: KVM/vCPU异常     → scripts/branch_Q_kvm.sh"
  BRANCH_MAP["acpi_.*error|AE_BAD_ADDRESS|ACPI Error"]="分支R: ACPI固件异常     → scripts/branch_R_acpi.sh"
  BRANCH_MAP["migrate_pages.*fail|offline_pages.*error|page migration"]="分支S: 热插拔/页迁移    → scripts/branch_S_hotplug.sh"
  BRANCH_MAP["memory_failure|hwpoison|HardwareCorrupted"]="分支F+V: 内存硬件故障   → scripts/branch_F_memory_ue.sh / branch_V_bit_flip.sh"

  for pattern in "${!BRANCH_MAP[@]}"; do
    if grep -iEq "${pattern}" "$filtered_log" 2>/dev/null; then
      echo "${BRANCH_MAP[$pattern]}"
    fi
  done

  # 分支V：疑似 Bit Flip
  local BIT_FLIP_PATTERN="paging request|Data Abort|unable to handle kernel paging request"
  BIT_FLIP_PATTERN+="|spurious page fault|bad area|bad page state"
  BIT_FLIP_PATTERN+="|invalid opcode|undefined instruction|general protection fault|trap: invalid opcode"
  BIT_FLIP_PATTERN+="|list_del corruption|list_add corruption|slab corruption"
  BIT_FLIP_PATTERN+="|BUG: Bad page|Corrupted page table|corrupted stack end"
  BIT_FLIP_PATTERN+="|\(invalid\)|no return address|<no return>|bt: read error|cannot read"

  if grep -iEq "${BIT_FLIP_PATTERN}" "$filtered_log" 2>/dev/null; then
    echo "分支V: 疑似Bit Flip → scripts/branch_V_bit_flip.sh"
  fi

  # 手动/测试触发崩溃
  if grep -iEq "sysrq:.*trigger.*crash|sysrq.*triggered crash|panic.*sysrq" "$filtered_log" 2>/dev/null; then
    echo "分支W: 手动/测试触发崩溃（sysrq） → 无需分支脚本，查看日志确认触发原因"
  fi

  rm -f "$filtered_log"
}
