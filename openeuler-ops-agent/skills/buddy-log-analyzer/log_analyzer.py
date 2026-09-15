#!/usr/bin/env python3
"""
Log Analyzer Agent - 日志智能分析
基于 mini-swe-agent 极简理念：确定性规则 + AI推理
"""

import re
import sys
import json
import os
import time
import html
from pathlib import Path
from datetime import datetime
from collections import Counter, defaultdict
from dataclasses import dataclass, field, asdict
from typing import Optional, List

# ── 日志事件数据类（需在使用前定义）───────────────────────────────
@dataclass
class LogEvent:
    level: str          # ERROR / WARN / INFO
    message: str
    line_no: int
    timestamp: str = ""
    count: int = 1      # 相同事件出现次数

@dataclass
class AnalysisResult:
    file_path: str
    total_lines: int
    scan_time_ms: float
    critical: list = field(default_factory=list)   # P0
    warnings: list = field(default_factory=list)    # P1
    patterns: dict = field(default_factory=dict)    # 高频模式
    ai_analysis: str = ""                           # AI根因分析

# ── 自进化记忆层 ───────────────────────────────────────────────
_HISTORY_DIR = Path.home() / ".log-analyzer"
_HISTORY_FILE = _HISTORY_DIR / "history.json"
_MAX_HISTORY = 50  # 最多保留最近50条分析记录


def _ensure_history_dir():
    _HISTORY_DIR.mkdir(parents=True, exist_ok=True)


def load_history(limit: int = 10) -> List[dict]:
    """加载最近的N条分析记忆"""
    _ensure_history_dir()
    if not _HISTORY_FILE.exists():
        return []
    try:
        records = json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
        return records[-limit:]
    except Exception:
        return []


def save_analysis_to_history(result: AnalysisResult):
    """把本次分析结果存入记忆，供下次分析参考"""
    _ensure_history_dir()
    
    # 读取旧记录
    records = []
    if _HISTORY_FILE.exists():
        try:
            records = json.loads(_HISTORY_FILE.read_text(encoding="utf-8"))
        except Exception:
            records = []
    
    # 构建本次记录
    entry = {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "file": result.file_path,
        "total_lines": result.total_lines,
        "critical_count": len(result.critical),
        "warning_count": len(result.warnings),
        "top_patterns": {k: v for k, v in list(result.patterns.items())[:5]},
        "top_errors": [e.message[:120] for e in result.critical[:3]],
    }
    
    records.append(entry)
    
    # 滑动窗口：只保留最近_MAX_HISTORY条
    records = records[-_MAX_HISTORY:]
    
    _HISTORY_FILE.write_text(
        json.dumps(records, ensure_ascii=False, indent=2),
        encoding="utf-8"
    )


def format_history_for_prompt() -> str:
    """把历史记录格式化为提示词上下文"""
    history = load_history(limit=5)
    if not history:
        return ""
    
    lines = ["\n📋 历史分析记录（供参考）："]
    for h in history:
        dt = h["ts"][:16].replace("T", " ")
        lines.append(f"  · {dt} | {h['file']} | P0:{h['critical_count']} 警告:{h['warning_count']}")
        for err in h.get("top_errors", []):
            lines.append(f"    - {err}")
    return "\n".join(lines)


# ── Webhook 安全校验 ────────────────────────────────────────────
_ALLOWED_WEBHOOK_SCHEMES = ("http", "https")
# 禁止的IP段（内网/本地/特殊用途）
_BLOCKED_IP_PATTERNS = (
    re.compile(r'^127\.\d+\.\d+\.\d+$'),       # localhost
    re.compile(r'^10\.\d+\.\d+\.\d+$'),          # 10.x.x.x
    re.compile(r'^172\.(1[6-9]|2\d|3[01])\.\d+\.\d+$'),  # 172.16-31.x.x
    re.compile(r'^192\.168\.\d+\.\d+$'),         # 192.168.x.x
    re.compile(r'^169\.254\.\d+\.\d+$'),         # link-local
    re.compile(r'^0\.\d+\.\d+\.\d+$'),           # 0.x.x.x
    re.compile(r'^localhost$', re.I),            # localhost 主机名
)

def validate_webhook_url(url: str) -> str:
    """校验Webhook URL，返回规范化URL或抛异常"""
    from urllib.parse import urlparse
    parsed = urlparse(url)
    if parsed.scheme not in _ALLOWED_WEBHOOK_SCHEMES:
        raise ValueError(f"Webhook 只支持 http/https，不支持 {parsed.scheme}")
    if not parsed.netloc:
        raise ValueError("Webhook URL 缺少域名")

    # 禁止内网IP（SSRF防护）
    host = parsed.hostname or ""
    for pat in _BLOCKED_IP_PATTERNS:
        if pat.match(host):
            raise ValueError(f"Webhook 不允许访问内网地址: {host}")

    return url

# ── 告警输出层 ─────────────────────────────────────────────────
def build_json_report(result: AnalysisResult) -> dict:
    """构建结构化JSON报告"""
    return {
        "ts": datetime.now().isoformat(timespec="seconds"),
        "file": result.file_path,
        "total_lines": result.total_lines,
        "scan_time_ms": round(result.scan_time_ms, 1),
        "summary": {
            "critical_count": len(result.critical),
            "warning_count": len(result.warnings),
            "high_freq_patterns": result.patterns,
        },
        "critical": [
            {"level": e.level, "line": e.line_no, "message": e.message[:300], "ts": e.timestamp}
            for e in result.critical[:20]
        ],
        "warnings": [
            {"level": w.level, "line": w.line_no, "message": w.message[:300], "ts": w.timestamp}
            for w in result.warnings[:20]
        ],
        "ai_analysis": result.ai_analysis,
    }


# ── 告警去重 ────────────────────────────────────────────────────
_ALERT_COOLDOWN_FILE = Path.home() / ".log-analyzer" / "alert_cooldown.json"
_ALERT_COOLDOWN_MINUTES = 5  # 同一错误5分钟内不重复告警

def _is_alert_suppressed(result: AnalysisResult) -> bool:
    """检查是否在冷却期内（同错误5分钟内不重复告警）"""
    if not _ALERT_COOLDOWN_FILE.exists():
        return False
    try:
        cooldown = json.loads(_ALERT_COOLDOWN_FILE.read_text(encoding="utf-8"))
        now = datetime.now().timestamp()
        for entry in cooldown:
            # 同文件名 + 同错误关键词
            if (entry.get("file") == result.file_path
                    and entry.get("p0_count") == len(result.critical)):
                elapsed = now - entry.get("ts", 0)
                if elapsed < _ALERT_COOLDOWN_MINUTES * 60:
                    return True
        return False
    except Exception:
        return False

def _save_alert_sent(result: AnalysisResult):
    """记录本次告警（原子写入，防多进程竞态）"""
    _ensure_history_dir()
    lock_path = _ALERT_COOLDOWN_FILE.with_suffix('.lock')
    tmp_path = _ALERT_COOLDOWN_FILE.with_suffix('.tmp')

    def _atomic_write(cooldown: list):
        tmp_path.write_text(json.dumps(cooldown), encoding="utf-8")
        tmp_path.replace(_ALERT_COOLDOWN_FILE)

    try:
        # 简单锁：创建.lock文件表示正在写入
        for _wait in range(10):  # 最多等待1秒
            if not lock_path.exists():
                try:
                    lock_path.touch()
                    break
                except FileExistsError:
                    pass
            time.sleep(0.1)
        else:
            # 超时：直接跳过（不阻塞主流程）
            return

        cooldown = []
        if _ALERT_COOLDOWN_FILE.exists():
            try:
                cooldown = json.loads(_ALERT_COOLDOWN_FILE.read_text(encoding="utf-8"))
            except Exception:
                cooldown = []
        cooldown.append({
            "ts": datetime.now().timestamp(),
            "file": result.file_path,
            "p0_count": len(result.critical),
        })
        cooldown = cooldown[-20:]
        _atomic_write(cooldown)
    except Exception:
        pass
    finally:
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass

def send_alert(result: AnalysisResult,
               report_path: Optional[str] = None,
               webhook_url: Optional[str] = None,
               output_format: str = "text"):
    """
    发送告警：写JSON报告 + 可选webhook推送。
    仅在有P0错误时触发。
    """
    if not result.critical:
        return

    # 冷却期检查
    if _is_alert_suppressed(result):
        print(f"⏳ 告警冷却中（{_ALERT_COOLDOWN_MINUTES}分钟内不重复告警）")
        return

    _save_alert_sent(result)
    report = build_json_report(result)
    report_json = json.dumps(report, ensure_ascii=False, indent=2)

    # 1. 写文件
    if report_path:
        # 校验报告路径合法性，防止写到 cwd 之外
        try:
            p = safe_resolve(report_path)
        except ValueError as e:
            print(f"⚠️  报告路径不安全: {e}")
            return
        p.parent.mkdir(parents=True, exist_ok=True)
        ext = p.suffix.lower()
        if ext == ".csv":
            p.write_text(format_csv(result), encoding="utf-8")
        elif ext == ".html":
            p.write_text(format_html(result), encoding="utf-8")
        else:
            p.write_text(report_json, encoding="utf-8")
        print(f"📄 报告已写入: {report_path}")

    # 2. Webhook推送
    if webhook_url:
        try:
            webhook_url = validate_webhook_url(webhook_url)
        except ValueError as e:
            print(f"⚠️  Webhook URL 校验失败: {e}")
            return
        
        try:
            import requests
            # 重试退避：最多3次，间隔1s/2s/4s
            for attempt in range(3):
                try:
                    resp = requests.post(
                        webhook_url,
                        data=report_json.encode("utf-8"),
                        headers={"Content-Type": "application/json"},
                        timeout=10,
                    )
                    if resp.status_code < 400:
                        print(f"🔔 Webhook推送成功 (HTTP {resp.status_code})")
                        break
                    print(f"⚠️  Webhook返回异常 (HTTP {resp.status_code}): {resp.text[:100]}"
                          + (f"，重试中... ({attempt+1}/3)" if attempt < 2 else ""))
                except requests.exceptions.Timeout:
                    if attempt < 2:
                        print(f"⚠️  Webhook超时，重试中... ({attempt+1}/3)")
                    else:
                        print(f"⚠️  Webhook超时，已放弃")
                        raise
                    time.sleep(2 ** attempt)
                    continue
                if resp.status_code >= 500 and attempt < 2:
                    time.sleep(2 ** attempt)
                    continue
                break
        except Exception as e:
            print(f"⚠️  Webhook推送失败: {e}")

# ── 确定性规则（P0/P1 快速提取）──────────────────────────────
# 用 \b 词边界避免匹配 variable.critical 这类变量名
CRITICAL_PATTERNS = [
    (re.compile(r'\b(ERROR|CRITICAL|FATAL)\b', re.I), "P0"),
    (re.compile(r'\b(OutOfMemory|Segmentation fault|Killed)\b', re.I), "P0"),
    (re.compile(r'(Connection refused|Connection reset|ECONNREFUSED)', re.I), "P0"),
    (re.compile(r'(Traceback|at .+ line \d+)', re.I), "P0"),
    (re.compile(r'\bHTTP [45]\d\d\b', re.I), "P0"),
]

WARNING_PATTERNS = [
    (re.compile(r'\b(WARN|WARNING)\b', re.I), "P1"),
    (re.compile(r'(timeout|timed out|Slow query)', re.I), "P1"),
    (re.compile(r'(retry|Retry attempt)', re.I), "P1"),
    (re.compile(r'\bdeprecated\b', re.I), "P1"),
    (re.compile(r'(disk|memory|cpu).+(high|full|low|warn)', re.I), "P1"),
]

# 代码行特征：跳过 .py/.js/.java/.go 等源码文件中的误报
# 启发式：行首是常见语句关键字（而非时间戳）
_CODE_LINE_PREFIXES = (
    "#",   # 代码注释（含Python docstring开头）
    "if ", "for ", "while ", "def ", "class ", "return ", "import ",
    "from ", "try:", "except", "with ", "async ", "async def ",
    "elif ", "else:", "finally:", "raise ", "yield ", "await ",
    "@",  # 装饰器
)


def _is_likely_code_line(line: str) -> bool:
    """启发式判断：是否是代码行（而非日志行）"""
    stripped = line.strip()
    # 1. 行首是Python关键字 → 跳过
    if stripped.startswith(_CODE_LINE_PREFIXES):
        return True
    # 2. f-string/字符串拼接（常见于日志构建代码）
    # 更严格：必须同时有 f" 或 f' 才认为是 f-string，避免误判含 { 的普通日志
    if (('f"' in stripped or "f'" in stripped)
            and ('{' in stripped or '.append(' in stripped or '.write(' in stripped)):
        return True
    # 3. 赋值语句（var = 或 var.method()）
    if re.match(r'^\s*[a-zA-Z_][a-zA-Z0-9_]*\s*(\.|:|\[|=)', stripped):
        return True
    return False

TIMESTAMP_RE = re.compile(
    r'\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}|'
    r'\d{2}/\w+/\d{4}:\d{2}:\d{2}:\d{2}|'
    r'\w{3}\s+\d+\s+\d{2}:\d{2}:\d{2}'
)

def extract_timestamp(line: str) -> str:
    m = TIMESTAMP_RE.search(line)
    return m.group(0) if m else ""

# ── 安全路径解析 ───────────────────────────────────────────────
MAX_FILE_SIZE = 500 * 1024 * 1024  # 500MB（大文件用流式读取）
_SMALL_FILE_THRESHOLD = 10 * 1024 * 1024  # 10MB以下直接读

def safe_resolve(path_str: str, base: str = os.getcwd()) -> Path:
    """安全路径解析，防止目录遍历攻击"""
    try:
        p = Path(path_str).resolve()
        # 相对路径：限制在当前目录内；绝对路径：直接放行
        if not Path(path_str).is_absolute():
            b = Path(base).resolve()
            if not str(p).startswith(str(b)):
                raise ValueError("路径不允许访问目录外资源")
        if p.is_symlink():
            raise ValueError("拒绝符号链接")
        return p
    except (OSError, ValueError) as e:
        raise ValueError(f"路径无效: {e}")

def _stream_lines(path: Path, tail: int = 0):
    """
    流式读取文件行，按需处理 tail。
    - tail=0：全量读取（小文件）
    - tail>0 且文件<10MB：全量读再切尾部
    - tail>0 且文件>=10MB：环形缓冲保留最后 tail 行
    """
    file_size = path.stat().st_size
    encoding = 'utf-8'

    if tail > 0 and file_size >= _SMALL_FILE_THRESHOLD:
        # 大文件 tail：环形缓冲，只保留最后 N 行
        buf: List[str] = []
        n = tail
        with open(path, 'r', encoding=encoding, errors='replace') as f:
            for raw in f:
                buf.append(raw.rstrip('\n\r'))
                if len(buf) > n:
                    buf.pop(0)
        yield from enumerate(buf, 1)
    else:
        # 小文件或有 --tail 限制：一次性读
        lines = path.read_text(encoding=encoding, errors='replace').splitlines()
        if tail > 0:
            lines = lines[-tail:]
        yield from enumerate(lines, 1)

def scan_file(file_path: str, tail: int = 0) -> AnalysisResult:
    """扫描日志文件，提取关键事件"""
    import time
    start = time.time()
    
    # 安全路径校验
    try:
        path = safe_resolve(file_path)
    except ValueError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
    
    if not path.exists() or not path.is_file():
        print("[ERROR] file not found or not a valid file")
        sys.exit(1)
    
    file_size = path.stat().st_size
    if file_size > MAX_FILE_SIZE:
        print(f"❌ 文件过大 ({file_size/1024/1024:.0f}MB)，最大支持500MB")
        sys.exit(1)
    
    result = AnalysisResult(
        file_path=file_path,
        total_lines=0,
        scan_time_ms=0
    )
    
    pattern_counter = Counter()
    seen_messages = set()
    
    # ── 多行堆栈合并状态机 ─────────────────────────────────────
    stack_buffer: List[str] = []
    stack_start_line = 0
    total_lines = 0
    
    def _flush_stack(line_no: int):
        """把堆栈缓冲合并为一个事件"""
        merged = " | ".join(stack_buffer)
        key = merged[:80]
        pattern_counter[key] += 1
        if key not in seen_messages:
            seen_messages.add(key)
            result.critical.append(LogEvent(
                level="P0",
                message=merged[:300],
                line_no=stack_start_line,
                timestamp=""
            ))
        stack_buffer.clear()
    
    for i, line in _stream_lines(path, tail):
        total_lines += 1
        stripped = line.strip()
        if not stripped:
            if stack_buffer:
                _flush_stack(i)
            continue
        
        if _is_likely_code_line(stripped):
            if stack_buffer:
                _flush_stack(i)
            continue
        
        is_stack_line = bool(
            re.search(r'(\bat\s+\S+|File "|CalledFrom|^\s+at\s)', stripped)
        )
        is_traceback = re.search(r'\b(Traceback|Exception|Error|CRITICAL|FATAL)\b', stripped, re.I)
        
        if is_stack_line and (stack_buffer or is_traceback):
            stack_buffer.append(stripped[:150])
            continue
        
        if is_traceback and not stack_buffer:
            stack_start_line = i
            stack_buffer.append(stripped[:150])
            continue
        
        if stack_buffer:
            _flush_stack(i)
        
        ts = extract_timestamp(stripped)
        
        for pat, level in CRITICAL_PATTERNS:
            if pat.search(stripped):
                key = stripped[:80]
                pattern_counter[key] += 1
                if key not in seen_messages:
                    seen_messages.add(key)
                    result.critical.append(LogEvent(
                        level="P0",
                        message=stripped[:200],
                        line_no=i,
                        timestamp=ts
                    ))
                break
        
        # P1: 警告
        for pat, level in WARNING_PATTERNS:
            if pat.search(stripped):
                key = stripped[:80]
                pattern_counter[key] += 1
                if key not in seen_messages:
                    seen_messages.add(key)
                    result.warnings.append(LogEvent(
                        level="P1",
                        message=stripped[:200],
                        line_no=i,
                        timestamp=ts
                    ))
                break
    
    # 文件结束时 flush 剩余堆栈
    if stack_buffer:
        _flush_stack(total_lines)
    
    result.total_lines = total_lines
    
    # 高频模式（出现3次以上的异常）
    result.patterns = {
        msg: count for msg, count in pattern_counter.most_common(10)
        if count >= 3
    }
    
    result.scan_time_ms = (time.time() - start) * 1000
    return result

SYSTEM_PROMPT = """你是一个经验丰富的SRE工程师，专门从日志中快速定位根因并给出可执行的修复建议。

分析规则（按顺序执行）：
1. **先看历史记录**：如果提供了历史数据，先对比"本次"和"上次"的差异——新增的错误是重点，减少的错误说明已有改善
2. 再找时间最早的错误——它往往是触发后续连锁故障的根因
3. 重点关注重复出现 ≥3 次的模式，单次偶发可以降低优先级
4. 识别因果链：A导致B导致C，要从A开始修，不要只修C
5. 常见根因对照（不限于此，请自主推理）：
   - Connection refused / ECONNREFUSED → 目标服务未启动或端口被防火墙拦截
   - OutOfMemory / heap space → 内存泄漏或配置堆内存过小
   - Slow query / timeout → 缺索引、数据量爆炸、或依赖服务响应慢
   - Traceback / Exception → 边界条件未处理，查堆栈定位具体代码行
   - HTTP 5xx → 应用内部错误，结合应用日志排查
   - Retry exhausted → 下游服务不稳定，考虑熔断降级
   - Disk/Memory full → 容量规划问题，立即清理或扩容
6. 如果不确定，用"可能"标注，不要给出不确定的结论
7. 如果日志无异常，直接说"✅ 日志整体健康，无需处理"

输出格式（严格遵守，控制在8句话以内）：
🔍 根因：[1-2句，说清楚是什么问题]
🔧 修复：[2-3个具体步骤，可操作]
🛡️ 预防：[1句，如果有意义的话]"""

def ai_analyze(result: AnalysisResult, model: Optional[str] = None) -> str:
    """AI深度分析根因"""
    sf_key = os.getenv("SILICONFLOW_API_KEY")
    oai_key = os.getenv("OPENAI_API_KEY")
    api_key = sf_key or oai_key
    
    if not result.critical and not result.warnings:
        return "✅ 日志整体健康，无需处理"
    
    summary = _build_summary(result)
    history_ctx = format_history_for_prompt()
    
    if not api_key:
        # 无API时：把摘要 + 规则一起告知用户
        return (f"⚠️  未配置 API Key，无法进行 AI 根因分析。\n"
                f"请设置 SILICONFLOW_API_KEY 或 OPENAI_API_KEY。\n\n"
                f"原始摘要：\n{summary}")
    
    try:
        import requests
        model_name = model or "deepseek-ai/DeepSeek-V2.5"
        
        user_content = f"请分析以下日志摘要：\n\n{summary}"
        if history_ctx:
            user_content += f"\n{history_ctx}\n\n请结合历史记录，重点分析本次新增的错误模式。"
        
        payload = {
            "model": model_name,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_content}
            ],
            "max_tokens": 400,
            "temperature": 0.2
        }
        
        base_url = "https://api.siliconflow.cn/v1" if sf_key else "https://api.openai.com/v1"
        resp = requests.post(
            f"{base_url}/chat/completions",
            json=payload,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=30
        )
        
        if resp.status_code == 200:
            try:
                data = resp.json()
                analysis = (
                    (data.get("choices") or [{}])[0]
                    .get("message", {})
                    .get("content", "")
                )
                if not analysis:
                    return "⚠️  API 返回内容为空，请检查模型是否正常"
            except (KeyError, IndexError, ValueError) as e:
                return f"⚠️  响应解析失败: {e}，原始摘要：\n{summary}"
            # 分析成功后自动保存记忆
            save_analysis_to_history(result)
            return analysis
        return f"⚠️  API 调用失败 (HTTP {resp.status_code})，请检查 Key 是否有效。"
    except json.JSONDecodeError:
        return f"⚠️  API 返回了无效 JSON，原始摘要：\n{summary}"
    except Exception:
        return f"⚠️  网络异常，AI 分析不可用。原始摘要：\n{summary}"

def _build_summary(result: AnalysisResult) -> str:
    """构建日志摘要供AI分析"""
    lines = [f"文件: {result.file_path}，共 {result.total_lines} 行\n"]
    
    if result.critical:
        lines.append(f"严重错误 ({len(result.critical)} 个):")
        for e in result.critical[:5]:
            ts = f"[{e.timestamp}] " if e.timestamp else ""
            lines.append(f"  {ts}{e.message}")
    
    if result.warnings:
        lines.append(f"\n警告 ({len(result.warnings)} 个):")
        for w in result.warnings[:5]:
            ts = f"[{w.timestamp}] " if w.timestamp else ""
            lines.append(f"  {ts}{w.message}")
    
    if result.patterns:
        lines.append("\n高频模式:")
        for msg, count in list(result.patterns.items())[:5]:
            lines.append(f"  × {count}: {msg}")
    
    return "\n".join(lines)


def format_report(result: AnalysisResult) -> str:
    """格式化输出报告"""
    lines = [
        f"\n📊 日志分析报告",
        f"{'━' * 50}",
        f"文件: {result.file_path}",
        f"总行数: {result.total_lines:,} 行 | 扫描耗时: {result.scan_time_ms:.0f}ms",
        ""
    ]
    
    if result.critical:
        lines.append(f"🔴 严重 (P0) — {len(result.critical)} 个")
        for e in result.critical[:8]:
            ts = f"[{e.timestamp}] " if e.timestamp else f"[行 {e.line_no}] "
            lines.append(f"  {ts}{e.message[:100]}")
        if len(result.critical) > 8:
            lines.append(f"  ... 还有 {len(result.critical)-8} 个")
    else:
        lines.append("✅ 无严重错误 (P0)")
    
    lines.append("")
    
    if result.warnings:
        lines.append(f"🟡 警告 (P1) — {len(result.warnings)} 个")
        for w in result.warnings[:5]:
            ts = f"[{w.timestamp}] " if w.timestamp else f"[行 {w.line_no}] "
            lines.append(f"  {ts}{w.message[:100]}")
        if len(result.warnings) > 5:
            lines.append(f"  ... 还有 {len(result.warnings)-5} 个")
    
    if result.patterns:
        lines.append(f"\n📈 高频模式 (出现≥3次)")
        for msg, count in list(result.patterns.items())[:5]:
            lines.append(f"  × {count}  {msg[:80]}")
    
    if result.ai_analysis:
        lines.append(f"\n🧠 AI 根因分析")
        lines.append(f"{'─' * 40}")
        lines.append(result.ai_analysis)
    
    lines.append(f"\n{'━' * 50}")
    return "\n".join(lines)


def format_csv(result: AnalysisResult) -> str:
    """输出 CSV 格式报告"""
    rows = ["level,line_no,message,timestamp"]

    def _csv_cell(text: str) -> str:
        """CSV单元格：转义换行、引号、双引号"""
        text = text[:200].replace('\n', '\\n').replace('\r', '\\r').replace('"', '""')
        return f'"{text}"'

    for e in result.critical:
        rows.append(f"P0,{e.line_no},{_csv_cell(e.message)},{_csv_cell(e.timestamp)}")
    for w in result.warnings:
        rows.append(f"P1,{w.line_no},{_csv_cell(w.message)},{_csv_cell(w.timestamp)}")
    return "\n".join(rows)


def format_html(result: AnalysisResult) -> str:
    """输出 HTML 格式报告"""
    dt = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rows = ""
    for e in result.critical:
        rows += f"<tr><td style='color:red'>P0</td><td>{e.line_no}</td>"
        rows += f"<td>{html.escape(e.message[:200])}</td><td>{html.escape(e.timestamp)}</td></tr>\n"
    for w in result.warnings:
        rows += f"<tr><td style='color:orange'>P1</td><td>{w.line_no}</td>"
        rows += f"<td>{html.escape(w.message[:200])}</td><td>{html.escape(w.timestamp)}</td></tr>\n"
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><title>Log Analysis - {dt}</title>
<style>
  body{{font-family:monospace;padding:20px}}
  table{{border-collapse:collapse;width:100%}}
  th,td{{border:1px solid #ddd;padding:8px;text-align:left}}
  th{{background:#333;color:#fff}}
  tr:nth-child(even){{background:#f9f9f9}}
</style></head>
<body>
<h2>📊 Log Analyzer Report</h2>
<p><b>File:</b> {result.file_path} | <b>Lines:</b> {result.total_lines:,} | <b>Scan:</b> {result.scan_time_ms:.0f}ms | <b>Time:</b> {dt}</p>
<p><b>P0:</b> {len(result.critical)} | <b>P1:</b> {len(result.warnings)}</p>
<table><thead><tr><th>Level</th><th>Line</th><th>Message</th><th>Timestamp</th></tr></thead>
<tbody>{rows or '<tr><td colspan="4">No issues found</td></tr>'}
</tbody></table>
</body></html>"""

def analyze(file_path: str, tail: int = 0, no_ai: bool = False,
             model: Optional[str] = None,
             report_path: Optional[str] = None,
             webhook_url: Optional[str] = None,
             grep: Optional[str] = None,
             exclude: Optional[str] = None,
             output_format: str = "text"):
    """主分析入口"""
    print(f"🔍 扫描 {file_path}...")
    result = scan_file(file_path, tail)
    
    # grep 过滤
    if grep:
        import re as _re
        _pat = _re.compile(grep, _re.I)
        before = len(result.critical), len(result.warnings)
        result.critical = [e for e in result.critical if _pat.search(e.message)]
        result.warnings = [w for w in result.warnings if _pat.search(w.message)]
        if before != (len(result.critical), len(result.warnings)):
            print(f"🔍 grep \"{grep}\" 过滤: P0 {before[0]}→{len(result.critical)}, P1 {before[1]}→{len(result.warnings)}")
    
    if exclude:
        import re as _re
        _pat = _re.compile(exclude, _re.I)
        before = len(result.critical), len(result.warnings)
        result.critical = [e for e in result.critical if not _pat.search(e.message)]
        result.warnings = [w for w in result.warnings if not _pat.search(w.message)]
        if before != (len(result.critical), len(result.warnings)):
            print(f"🔍 exclude \"{exclude}\" 过滤: P0 {before[0]}→{len(result.critical)}, P1 {before[1]}→{len(result.warnings)}")
    
    if not no_ai:
        result.ai_analysis = ai_analyze(result, model=model)
    
    # 按格式输出
    if output_format == "csv":
        print(format_csv(result))
    elif output_format == "html":
        print(format_html(result))
    else:
        print(format_report(result))
    
    # 告警：有P0错误时触发
    send_alert(result, report_path=report_path, webhook_url=webhook_url)
    
    return 1 if result.critical else 0

def main():
    import argparse
    parser = argparse.ArgumentParser(description="Log Analyzer - 日志智能分析")
    parser.add_argument("command", choices=["analyze", "watch"], help="命令 (watch = 实时监控)")
    parser.add_argument("path", help="日志文件路径")
    parser.add_argument("--tail", type=int, default=0, help="只分析最后N行")
    parser.add_argument("--no-ai", action="store_true", help="禁用AI分析（仅本地规则）")
    parser.add_argument("--model", default="deepseek-ai/DeepSeek-V2.5", help="AI模型（默认: deepseek-ai/DeepSeek-V2.5）")
    parser.add_argument("--report", default=None, help="告警报告输出路径（JSON）")
    parser.add_argument("--webhook", default=None, help="告警webhook地址（POST JSON）")
    parser.add_argument("--grep", default=None, help="只显示匹配关键词的事件")
    parser.add_argument("--exclude", default=None, help="排除匹配关键词的事件")
    parser.add_argument("--format", choices=["text","csv","html"], default="text", help="输出格式（默认: text）")
    
    args = parser.parse_args()
    
    if args.command == "watch":
        import time
        watch(args.path, tail=args.tail, no_ai=args.no_ai, model=args.model)
        return
    
    if args.command == "analyze":
        # 支持目录（扫描所有.log文件）
        p = Path(args.path)
        if p.is_dir():
            log_files = list(p.glob("**/*.log")) + list(p.glob("**/*.txt"))
            if not log_files:
                print(f"目录中没有找到日志文件: {args.path}")
                sys.exit(1)
            any_critical = False
            for f in log_files[:5]:  # 最多5个文件
                rc = analyze(str(f), args.tail, args.no_ai, args.model,
                             args.report, args.webhook, args.grep, args.exclude, args.format)
                any_critical = any_critical or (rc == 1)
            sys.exit(1 if any_critical else 0)
        else:
            sys.exit(analyze(args.path, args.tail, args.no_ai, args.model,
                             args.report, args.webhook, args.grep, args.exclude, args.format))

if __name__ == "__main__":
    main()

# ── tail -f 实时监控 ──────────────────────────────────────────
def watch(file_path: str, tail: int = 100, interval: float = 2.0,
           no_ai: bool = False, model: Optional[str] = None):
    """实时监控日志文件，有新增ERROR时告警（增量读取）"""
    import time
    print(f"👁️  监控 {file_path} (每 {interval}s 轮询，按 Ctrl+C 停止)")
    print(f"   初始显示最近 {tail} 行...\n")
    
    last_pos = 0  # 上次读取的文件偏移量
    prev_tail_lines: List[str] = []  # 上次的尾部行（用于去重）
    
    # 首次读取：填充 prev_tail_lines
    try:
        p = safe_resolve(file_path)
        if p.exists() and p.is_file():
            with open(p, 'r', encoding='utf-8', errors='replace') as f:
                all_lines = f.readlines()
                prev_tail_lines = [l.rstrip('\n\r') for l in all_lines[-tail:]]
                last_pos = p.stat().st_size
    except Exception:
        pass
    
    while True:
        try:
            p = safe_resolve(file_path)
            if not (p.exists() and p.is_file()):
                time.sleep(interval)
                continue
            
            size = p.stat().st_size
            if size > MAX_FILE_SIZE:
                print(f"\n⚠️  文件超过 {MAX_FILE_SIZE/1024/1024:.0f}MB，停止监控")
                break
            
            # 有新增内容
            if size > last_pos:
                new_lines: List[str] = []
                with open(p, 'r', encoding='utf-8', errors='replace') as f:
                    f.seek(last_pos)  # 从上次位置开始读
                    for raw in f:
                        line = raw.rstrip('\n\r')
                        if line and line not in prev_tail_lines:
                            new_lines.append(line)
                
                last_pos = size
                
                # 更新尾部缓冲（滑动窗口）
                prev_tail_lines.extend(new_lines)
                if len(prev_tail_lines) > tail:
                    prev_tail_lines = prev_tail_lines[-tail:]
                
                # 有新增 ERROR 行才告警
                if new_lines:
                    error_lines = [l for l in new_lines
                                   if re.search(r'\b(ERROR|CRITICAL|FATAL)\b', l, re.I)]
                    if error_lines:
                        print(f"\n{'='*50}")
                        print(f"🆕 检测到更新: {datetime.now().strftime('%H:%M:%S')}, "
                              f"新增 {len(new_lines)} 行 (含 {len(error_lines)} 个错误)")
                        for el in error_lines[:5]:
                            print(f"   {el[:120]}")
                        if len(error_lines) > 5:
                            print(f"   ... 还有 {len(error_lines)-5} 个")
            
            time.sleep(interval)
        except KeyboardInterrupt:
            print("\n\n👋 停止监控")
            break
