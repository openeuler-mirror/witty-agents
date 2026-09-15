# openEuler Ops Agent

openEuler 运维智能助手，覆盖 16 个运维场景。在 opencode 中安装后，通过自然语言直接对话使用。

## 前置要求

| 依赖 | 最低版本 | 说明 |
|------|---------|------|
| Node.js | >= 18.18.0 | npm 全局安装需要 |
| Python | >= 3.8 | experience-skill 运行环境 |
| uv | 最新版 | Python 包管理器（`pip install uv`） |
| opencode | 最新版 | Agent 运行平台 |
| curl | 任意 | 下载 skillhub CLI 安装脚本 |

安装前请确保 `~/.local/bin` 在 PATH 中（skillhub CLI 默认安装路径）：

```bash
echo 'export PATH="$HOME/.local/bin:$PATH"' >> ~/.bashrc
source ~/.bashrc
```

## 安装（统一双命令）

四个 Agent 统一为 `<agent>-setup` + `<agent>-configure` 两个命令：

```bash
npm install -g ./openeuler-ops-agent-2.0.0.tgz
openeuler-ops-setup install                     # 可选：在线准备 skillhub 与 10 个 Skill
openeuler-ops-configure install --target=opencode
```

`setup install` 会自动完成以下操作（**不写 opencode 配置**，注册统一由 configure 完成）：

| 步骤 | 操作 | 说明 |
|------|------|------|
| Step 1 | 检查/安装 **skillhub CLI** | 多路径搜索，不存在则自动下载安装并验证 |
| Step 2 | 初始化 **experience-skill** 知识库 | `uv sync` + `sync` 索引 |
| Step 3 | 安装 **10 个 Skill** | 通过 skillhub 安装到 opencode skills 目录 |

> **注意**：本 Agent 无 Python/后端服务。skillhub CLI 安装失败时 Step 3 会被跳过，Agent 仍可正常使用（知识检索降级为 openEuler MCP 实时查询）。手动安装 skillhub 后重新运行 `openeuler-ops-setup install` 即可。

重启 opencode 后直接在对话中输入运维问题。

```bash
openeuler-ops-setup check                       # 只读验证安装完整性
openeuler-ops-configure install --target=opencode   # 重新注册 Agent（无需重新 setup）
```

## 架构

```
opencode 对话 (自然语言)
    │ 意图匹配 → 场景路由
    ▼
┌──────────────────────────────────────────────────┐
│              openeuler-ops Agent                  │
│              agent.md 驱动                         │
│                                                    │
│  ┌──────────┐  ┌──────────┐  ┌─────────────────┐ │
│  │ 知识库层  │  │ 技能层    │  │ 工作流层          │ │
│  │ experience│  │ skillhub │  │ 16 场景预定义流程 │ │
│  │ -skill    │  │ 10 Skills│  │ 步骤序列+决策分支  │ │
│  └──────────┘  └──────────┘  └─────────────────┘ │
│       │             │               │              │
│       └──── 半自动沉淀闭环 ────────┘              │
│    (brainstorming → experience-skill)              │
└──────────────────────────────────────────────────┘
    │
    ▼ 输出
  结构化排查步骤 + 可执行命令 + 根因分析 + 修复方案
```

**三层协作：**

| 层级 | 职责 | 实现 |
|------|------|------|
| 知识库层 | 检索已验证的运维经验，降低幻觉 | experience-skill Wiki/Skill Hub 三层 Fallback |
| 技能层 | 执行具体操作（命令、分析、远程） | skillhub 安装的 10 个原子 Skill |
| 工作流层 | 定义场景的完整排查路径 | agent.md 中的 16 个场景工作流 |

## 10 个集成 Skill

| Skill | 类型 | 能力 |
|-------|------|------|
| `agent-tools` | 核心 | 系统监控(cpu/mem/disk/io)、进程管理(ps/top/kill)、文件处理(find/df/du)、网络诊断(ping/ss/curl)、日志读取(tail/grep/journalctl) — **最常用，14/16 场景依赖** |
| `ssh-remote-skill` | 核心 | SSH 多服务器连接管理、远程命令执行、文件传输、系统监控、安全检查 |
| `ops-maintenance` | 专项 | 本地/远程/集群监控、安全审计、配置变更追踪、告警通知、定时巡检、Docker 健康巡检、SSL 证书监控（v3.1.0） |
| `log-analyzer` | 专项 | 日志统计、去重、错误模式识别、异常识别 — 四位一体纯本地分析（v1.0.2） |
| `buddy-log-analyzer` | 专项 | 确定性规则 + AI 推理的日志异常检测，基于 mini-swe-agent 理念，支持自进化 |
| `kubernetes` | 专项 | K8s 多 Agent 集群管理：orchestrator(编排) + cluster-ops(运维) + security(安全) + gitops(部署) + observability(可观测)（v2.1.0） |
| `docker-diag` | 专项 | Docker 容器日志高级分析，基于信号提取的诊断方法 |
| `summarize` | 元 | 诊断结论/巡检报告/长日志自动摘要 |
| `self-improvement` | 元 | 排查路径捕获 → Skill/Wiki 草稿生成 → 半自动沉淀（v3.0.24） |
| `skill-vetter` | 元 | Skill 安装前安全预审：风险信号检查、权限范围审计 |

## 可调用的 openEuler MCP 工具

Agent 可调用 openEuler 社区的实时数据接口：

| 工具 | 用途 |
|------|------|
| `get_cve_info` | CVE 安全漏洞列表与详情（CVSS 评分、受影响包） |
| `get_security_notice_info` | 安全公告列表与详情 |
| `get_bug_notice_info` | 缺陷公告列表与详情 |
| `get_forum_info` | 论坛帖子搜索（最新/热门/关键词） |
| `get_docs_search_content` | 官方文档内容全文搜索 |
| `get_package_info` | 软件包信息与发行版生命周期 |
| `get_compatibility_info` | 硬件兼容性测试查询 |
| `get_sig_info` | SIG 组信息与成员贡献统计 |
| `get_issue_info` / `get_pull_request_info` | 社区 Issue/PR 查询 |

---

## 16 个场景详解

### 1. 故障排查

**触发词：** 报错、异常、失败、宕机、crash、panic、OOM、卡死、起不来、不响应、排查、诊断

**工作流（5 步）：**

```
Step 1: 现象确认
  收集系统状态快照 → CPU/内存/磁盘/进程/负载
  远程场景自动启用 ssh-remote-skill
  同步检索 experience-skill Wiki Hub（关键词匹配历史案例）

Step 2: 日志收集
  log-analyzer: 统计 → 去重 → 错误模式识别
  buddy-log-analyzer: 确定性规则初筛 → AI 推理深度分析

Step 3: 根因判断
  有明确异常日志?
    ├─ 是 → 匹配 experience-skill 已知案例 → 直接出方案
    └─ 否 → 深度诊断（网络/存储/内核/资源 全面排查）

Step 4: 方案输出
  summarize 生成摘要
  输出: 故障时间线 | 根因结论 | 可执行修复命令 | 预防建议

Step 5: 知识沉淀
  新问题 → self-improvement 捕获路径 → brainstorming-v2 结构化
  → experience-skill 查重 → 人工 Review → 入库 → 下次复用
```

**依赖 Skill：** agent-tools, ssh-remote-skill, log-analyzer, buddy-log-analyzer, summarize

---

### 2. 日常巡检

**触发词：** 巡检、检查、健康、状态

```
Step 1: 资源巡检    → CPU/内存/磁盘/负载 (阈值: cpu>90% mem>85% disk>80% 告警)
Step 2: 硬件健康    → SMART 磁盘健康/温度/风扇
Step 3: 服务状态    → systemctl failed units / 关键服务运行态
Step 4: 内核日志    → dmesg error/warn 级别扫描
Step 5: 生成报告    → 健康评分(百分制) + 异常项列表(按严重度) + 趋势对比(vs 上次)
```

**依赖 Skill：** agent-tools, ops-maintenance, summarize

---

### 3. CVE 漏洞修复

**触发词：** CVE、漏洞、安全公告、补丁、patch

```
Step 1: CVE 扫描
  → get_cve_info list 模式扫描未修复 CVE
  → experience-skill Wiki 检索该 CVE 的历史修复记录

Step 2: 影响评估
  → get_cve_info detail 模式获取 CVSS 评分/受影响包
  → CVSS 降序排列，优先修复高危

Step 3: 修复方案选择
  ├─ 内核 CVE + 热补丁可用  → dnf hotupgrade（无需重启）
  ├─ 用户态 CVE + 热补丁可用 → dnf hotpatch（无需重启）
  ├─ 不支持热补丁           → dnf update（需规划维护窗口）
  └─ 容器场景               → 镜像重新构建

Step 4: 执行修复
  → agent-tools 执行 dnf/热补丁命令
  → ssh-remote-skill 多机批量操作
  → 失败自动回滚并通知

Step 5: 报告
  → 修复清单(成功/失败) | 修复方式 | 是否需重启 | 版本对比
```

**依赖 MCP：** get_cve_info, get_security_notice_info
**依赖 Skill：** agent-tools, ssh-remote-skill, summarize

---

### 4. 安全加固

**触发词：** 加固、harden、SELinux、防火墙、安全配置、基线

逐项检查并加固，可选自定义加固项列表：

```
基线检查   → sec_conf 工具一键检查
SELinux    → 模式切换(permissive→enforcing)、策略配置
防火墙     → firewalld zone/port/service 规则审计
内核参数   → sysctl 安全参数 (ASLR/rp_filter/syncookies/ptrace)
Secure Boot → UEFI 签名验证链 (RSA + SM2 国密)
磁盘加密   → LUKS2 + SM4-XTS 商密算法
SSH 加固   → 禁 root 登录/密钥认证/端口变更/审计配置
```

**输出：** 加固项列表(通过/未通过/已加固) | 未通过项修复建议 | 回滚方案

**依赖 Skill：** agent-tools, ops-maintenance
**依赖 MCP：** get_docs_search_content

---

### 5. 性能调优

**触发词：** 调优、性能、优化、慢、卡顿、瓶颈

```
Step 1: 负载分析
  CPU    → mpstat/perf top
  内存   → free/proc/meminfo
  磁盘   → iostat/iotop
  网络   → sar/ss

Step 2: 瓶颈定位
  → get_docs_search_content 检索官方调优指南
  → experience-skill Wiki 检索历史调优案例

Step 3: 调优方案
  → 输出：当前瓶颈分析 | 推荐调优参数 | 预期效果 | 回滚方案

Step 4: 使能验证
  → 应用参数并对比效果
  → 记录原始值，随时可回滚
```

**依赖 MCP：** get_docs_search_content
**依赖 Skill：** agent-tools, summarize

---

### 6. 存储管理

**触发词：** 存储、磁盘、LVM、扩容、缩容、分区、格式化、加密、配额

| 操作 | 命令流程 |
|------|---------|
| 扩容 | pvcreate → vgextend → lvextend → resize2fs/xfs_growfs |
| 缩容 | ⚠ 需备份+umount+fsck，谨慎执行 |
| 新盘添加 | pvcreate → vgextend → lvcreate → mkfs → mount → /etc/fstab |
| 故障替换 | 坏盘下线(pvremove/vgreduce) → 新盘上线(vgextend) → 数据重建 |
| 文件系统修复 | umount → fsck/xfs_repair → mount |
| 磁盘加密 | cryptsetup luksFormat → luksOpen → mkfs → mount |
| 配额管理 | quotacheck → edquota → quotaon |

**依赖 Skill：** agent-tools

---

### 7. 网络管理

**触发词：** 网络、不通、丢包、DNS、bond、VLAN、网卡、防火墙

```
连通性诊断 → ping/traceroute → 端口/路由/防火墙/DNS 逐层排查
IP 配置    → nmcli connection add/modify/delete
Bond 绑定  → mode 0-6 选择 + 从接口绑定
VLAN 子接口 → nmcli connection add type vlan + VLAN ID
防火墙     → firewall-cmd zone/service/port 规则配置
DNS        → resolv.conf → systemd-resolved → dig/nslookup 验证
```

**依赖 Skill：** agent-tools

---

### 8. 内核维护

**触发词：** 内核、kernel、kdump、sysctl、模块、modprobe、热升级

```
版本管理 → uname -r / grubby --default-kernel / grub 多版本切换
参数调整 → sysctl 在线调整 + sysctl -p 持久化
模块管理 → modprobe/lsmod/modinfo/rmmod + 签名验证
kdump    → crashkernel 预留 + systemctl status kdump + 转储分析
热升级   → 内核热升级工具 → 秒级重启+程序热迁移 (无需停机)
内核反馈优化 → PGO kernel → 为 MySQL/Nginx/Redis 等定向优化
```

**依赖 Skill：** agent-tools

---

### 9. 高可用与集群

**触发词：** 集群、HA、pacemaker、corosync、脑裂、K8s、kubernetes、节点

```
HA 集群：
  巡检        → pcs status / crm_mon
  节点管理    → pcs cluster node add/remove
  脑裂处理    → corosync-cfgtool / pcs quorum 检测与恢复
  热迁移      → pcs resource move / virt-manager

K8s 集群（kubernetes Skill 驱动）：
  巡检        → kubectl get nodes/pods
  节点管理    → kubeadm join / kubectl drain+delete
  扩缩容      → kubectl scale
  GitOps      → ArgoCD + Helm + Kustomize 部署管理
```

**依赖 Skill：** agent-tools, ssh-remote-skill, kubernetes

---

### 10. 容器与虚拟化

**触发词：** 容器、container、docker、iSulad、虚拟机、镜像、image、直通

```
引擎部署     → dnf install isulad/docker → 配置 → systemctl start
容器生命周期 → run/create/start/stop/rm + 资源限制(cgroup)
VM 管理      → libvirt XML 配置 + 启动/暂停/恢复/快照
镜像管理     → build/pull/push/tag → registry 对接
设备直通     → SR-IOV VF 直通 / VFIO 直通 / NPU 直通
安全容器     → Kata Containers → 虚拟化隔离
容器诊断     → docker-diag 信号提取分析
```

**支持运行时：** iSulad / Docker / StratoVirt / Kata Containers

**依赖 Skill：** agent-tools, kubernetes, docker-diag

---

### 11. 系统升级回滚

**触发词：** 升级、update、upgrade、更新、回滚、rollback、dnf

```
Step 1: 升级前准备
  → 记录当前版本 (uname -r / cat /etc/openEuler-release)
  → LVM 快照 / dnf history 备份

Step 2: 升级检查
  → dnf check-update
  → dnf upgrade-en --kabi-check kernel (内核兼容性)
  → 依赖冲突预览

Step 3: 执行升级
  → dnf update (支持 --skip-broken 跳过冲突包)
  → 失败: LVM 快照回退 / grub 旧内核引导

Step 4: 升级后验证
  → 内核版本 + systemctl failed 检查
  → 关键服务可用性
```

**依赖 MCP：** get_package_info
**依赖 Skill：** agent-tools

---

### 12. 备份恢复

**触发词：** 备份、backup、恢复、restore、快照、snapshot

```
全量备份  → tar/rsync/dump
LVM 快照  → lvcreate --snapshot → 只读挂载 → 备份
配置管理  → /etc 版本追踪 + git 管理
引导修复  → grub2-mkconfig → grub2-install → dracut --force
恢复演练  → 验证 RTO/RPO → 记录耗时
```

**依赖 Skill：** agent-tools

---

### 13. 账号权限

**触发词：** 用户、user、账号、密码、passwd、sudo、权限、ACL、组

```
用户创建   → useradd → passwd → 家目录
用户修改   → usermod → 组/Shell/过期时间
用户删除   → userdel -r → 清理家目录+邮件
密码策略   → chage 复杂度/过期规则 → /etc/login.defs
sudo 权限  → visudo → 角色分配
ACL       → setfacl/getfacl → 细粒度文件权限
```

**依赖 Skill：** agent-tools

---

### 14. 服务进程

**触发词：** 服务、service、systemctl、进程、process、cgroup、启动、自启

```
服务管理   → systemctl status/start/stop/restart/enable
服务诊断   → journalctl -u 查看日志 → 依赖检查 → 端口冲突排查
进程排查   → ps/top/pidstat/strace/lsof
资源限制   → systemctl set-property (CPUQuota=/MemoryMax=) → cgroup v2
自定义 Unit → 编写 .service/.timer 文件 → systemctl daemon-reload
```

**依赖 Skill：** agent-tools

---

### 15. 日志审计

**触发词：** 日志、log、journal、审计、audit、轮替、rotate

```
日志收集   → journalctl/rsyslog → /var/log/* 统一采集
轮替配置   → logrotate → 策略(按大小/按天/保留份数)
审计规则   → auditd → auditctl 文件监控
关键字告警 → ERROR/OOM/panic/segfault 等模式匹配
异常分析   → log-analyzer(统计+去重+错误) + buddy-log-analyzer(规则+AI)
```

**依赖 Skill：** agent-tools, log-analyzer, buddy-log-analyzer

---

### 16. 知识沉淀

**触发词：** 沉淀、记录、保存、经验

```
捕获路径 → 本次排查的现象+步骤+根因+方案
评估价值 → self-improvement 判断是否值得沉淀
结构化   → brainstorming-v2 选定沉淀类型:
           ├─ 排查流程 → experience-skill Skill Hub
           ├─ 参考资料 → experience-skill Wiki Hub
           ├─ 故障案例 → Wiki(type:case)
           └─ 配置模板 → Wiki(type:config)
查重入库 → experience-skill search → 已有相似?merge : create
         → add-experiences → sync → FTS5 索引 → 下次检索立即可用
```

---

## 知识库检索策略

每次执行场景工作流前，按优先级逐层检索经验，优先使用已验证的知识：

```
Layer 1: Wiki Hub (最可靠，人工验证过的参考文档)
  → experience-skill search-experiences --type WIKI --top-k 5
  命中？→ 直接使用

Layer 2: Skill Hub (已沉淀的排查流程)
  → experience-skill search-experiences --type SKILL --top-k 5
  命中？→ 参考流程执行

Layer 3: openEuler MCP 实时查询 (兜底)
  → get_forum_info / get_docs_search_content / get_cve_info
```

**Keywords 精确过滤：** `scenario:`(场景) | `version:`(版本) | `type:`(case/config/doc) | `component:`(kernel/network/storage) | `severity:`(critical/high/medium/low) | `arch:`(aarch64/x86_64)

---

## 交互规则

1. 接收问题 → 关键词匹配 → 场景路由
2. 信息足够：直接执行工作流；不足：1-2 轮澄清
3. 每个步骤执行前先检索经验库
4. 输出命令必须是可直接执行的完整命令，不用占位符
5. 有风险的操作（删除/缩容/升级）必须提示用户确认
6. 解决新问题后主动询问是否沉淀到 experience-skill

## 验证

```bash
openeuler-ops-setup check
```

预期输出：

```
[Skills]
  ✓ agent-tools
  ✓ ssh-remote-skill
  ✓ ops-maintenance
  ✓ log-analyzer
  ✓ kubernetes
  ✓ docker-diag
  ✓ self-improvement
  ✓ skill-vetter
  ✓ summarize
  ✓ buddy-log-analyzer

[experience-skill]
  ✓ experience-skill (pyproject.toml)

[Agent]
  ✓ agent.md (prompt)

[Config]
  ✓ opencode config
```

## 依赖

| 依赖 | 版本 | 说明 |
|------|------|------|
| Node.js | >= 18.18.0 | `homedir()` 需要此版本，`package.json` 中最低声明为 18.0.0 |
| Python | >= 3.8 + uv | experience-skill 运行环境 |
| opencode | 最新版 | Agent 运行平台 |
| skillhub CLI | 最新版 | install.sh 自动安装到 `~/.local/bin/skillhub` |
| experience-skill | 内置 | 路径：`/usr/share/witty/opencode/skills/experience_skill/` |

> **PATH 提示**：确保 `~/.local/bin` 在 PATH 中，否则 skillhub 命令不可用。
> ```bash
> export PATH="$HOME/.local/bin:$PATH"
> ```

## 常见问题

### skillhub CLI 安装失败

如果 curl 下载失败或网络受限，手动安装：

```bash
curl -fsSL https://skillhub-1388575217.cos.ap-guangzhou.myqcloud.com/install/install.sh | bash
export PATH="$HOME/.local/bin:$PATH"
skillhub --help
```

### Skill 安装后找不到

检查 skills 目录和 skillhub 可用性：

```bash
ls ~/.config/opencode/skills/
~/.local/bin/skillhub list --dir ~/.config/opencode/skills/
```

### experience-skill 未找到

Agent 将降级为 openEuler MCP 实时查询作为兜底，不影响基本使用。手动安装：

```bash
~/.local/bin/skillhub install experience-skill --namespace witty --dir /usr/share/witty/opencode/skills
```

### 重装/升级

```bash
openeuler-ops-configure install --target=opencode   # 仅更新 Agent 注册，不重新下载 Skill
openeuler-ops-setup install                          # 完整重装在线 Skill（不触碰注册配置）
```

## 基于的 openEuler 版本

openEuler 24.03 LTS SP4，通过 `keywords` 的 `version:` 字段兼容其他版本。

## License

木兰宽松许可证，第 2 版 (MulanPSL-2.0)

http://license.coscl.org.cn/MulanPSL2
