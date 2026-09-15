---
name: buddy-log-analyzer
description: |
  日志智能分析工具：确定性规则 + AI 推理（mini-swe-agent 极简理念）。
  对系统/应用日志做错误提取、模式聚类与根因定位，输出结构化分析结论。
  Triggers: 日志分析、分析 log、错误日志、日志排查、log analyzer。
---

# Log Analyzer Skill

日志智能分析工具，基于 mini-swe-agent 极简理念：确定性规则 + AI 推理。

## 安装

```bash
# 直接运行
python log_analyzer.py analyze /path/to/logfile.log

# 或安装到 PATH
pip install -e .
```

## 依赖

```bash
pip install requests
```

## 使用方法

### 基本分析

```bash
python log_analyzer.py analyze app.log
```

### 只看最后 N 行

```bash
python log_analyzer.py analyze app.log --tail 200
```

### 禁用 AI 分析（仅规则引擎）

```bash
python log_analyzer.py analyze app.log --no-ai
```

### 指定 AI 模型

```bash
python log_analyzer.py analyze app.log --model deepseek-ai/DeepSeek-V3
```

### 多格式输出

```bash
# CSV 格式
python log_analyzer.py analyze app.log --format csv

# HTML 格式
python log_analyzer.py analyze app.log --format html
```

### 关键词过滤

```bash
# 只显示包含 "memory" 的错误
python log_analyzer.py analyze app.log --grep memory

# 排除 "timeout" 相关
python log_analyzer.py analyze app.log --exclude timeout
```

### 实时监控（tail -f）

```bash
python log_analyzer.py watch /path/to/logfile.log
python log_analyzer.py watch app.log --tail 50 --interval 5
```

### 生成告警报告

```bash
python log_analyzer.py analyze app.log --report /tmp/report.json
python log_analyzer.py analyze app.log --report /tmp/report.csv
python log_analyzer.py analyze app.log --report /tmp/report.html
```

### Webhook 告警

```bash
python log_analyzer.py analyze app.log --webhook https://your-webhook-endpoint.com/alert
```

### 分析目录（批量）

```bash
python log_analyzer.py analyze /var/logs/
```

## 环境变量

```bash
# SiliconFlow API（推荐，免费额度充足）
export SILICONFLOW_API_KEY=sk-xxxx

# 或 OpenAI API
export OPENAI_API_KEY=sk-xxxx
```

## 错误等级

| 等级 | 说明 | 触发条件 |
|------|------|----------|
| P0 | 严重 | ERROR/CRITICAL/FATAL、OOM、连接拒绝、HTTP 4xx/5xx、Traceback |
| P1 | 警告 | WARN/WARNING、timeout、Slow query、重试、deprecated |

## 设计原则

1. **确定性规则优先**：正则匹配，无需 AI 即可工作
2. **AI 推理增强**：规则命中后用 LLM 做根因分析
3. **自进化记忆**：历史分析记录帮助发现趋势
4. **安全第一**：路径遍历防护、SSRF 防护、XSS 防护

## 架构

```
scan_file()          # 核心：流式扫描 + 状态机
  ├─ _stream_lines() # 环形缓冲，处理 tail + 大文件
  ├─ _is_likely_code_line() # 跳过源码文件误报
  ├─ CRITICAL_PATTERNS      # 预编译正则
  └─ WARNING_PATTERNS        # 预编译正则

ai_analyze()         # AI 深度分析（SiliconFlow / OpenAI）
send_alert()         # 告警：文件 + Webhook + 去重冷却
watch()              # tail -f 实时监控（seek 增量读取）
```

## 安全特性

- 相对路径限制在 cwd 内
- 拒绝符号链接
- Webhook 禁止内网地址（SSRF 防护）
- HTML 输出转义（XSS 防护）
- 告警文件原子写入（多进程安全）
