"""数据模型定义"""

from datetime import datetime, timezone
from typing import Optional

from uuid import uuid4
from pydantic import BaseModel, Field


def _utc_now() -> str:
    from datetime import datetime
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _uid() -> str:
    return str(uuid4())[:8]


class HostFeatures(BaseModel):
    """主机硬件信息"""
    host_name: str = Field(default="", description="主机名")
    machine_model: str = Field(default="", description="服务器型号及BIOS版本")
    kernel_version: str = Field(default="", description="内核版本")
    cpu_model: str = Field(default="", description="CPU型号")
    cpu_num: int = Field(default=0, description="CPU核数")
    memory_size: str = Field(default="", description="内存大小")
    uptime_seconds: int = Field(default=0, description="运行时长(秒)")
    vendor: str = Field(default="", description="厂商")
    modules: list[str] = Field(default_factory=list, description="内核模块列表")


class CrashFeatures(BaseModel):
    """宕机特征"""
    crash_time: str = Field(default="", description="宕机时间")
    crash_type: str = Field(default="", description="宕机类型")
    bug_type: str = Field(default="", description="bug分类")
    bug_key: str = Field(default="", description="bug关键字")
    bug: str = Field(default="", description="内核原始bug描述")
    bug_summary: str = Field(default="", description="问题摘要")
    rip: str = Field(default="", description="崩溃指令指针")
    rip_function: str = Field(default="", description="RIP函数名")
    rip_offset: str = Field(default="", description="RIP偏移量")
    call_trace: str = Field(default="", description="调用栈原始文本(内部)")
    call_trace_text: str = Field(default="", description="调用栈原始文本")
    call_trace_functions: list[str] = Field(default_factory=list, description="调用栈函数名列表(内部)")
    call_trace_signature: list[str] = Field(default_factory=list, description="调用栈函数名列表")
    kernel_version: str = Field(default="", description="内核版本")
    crash_cpu: int = Field(default=-1, description="崩溃CPU")
    crash_command: str = Field(default="", description="崩溃进程")
    related_modules: list[str] = Field(default_factory=list, description="关联模块")
    crash_log: str = Field(default="", description="崩溃日志片段")

    anomaly_features: dict = Field(default_factory=dict, description="额外异常特征: repeated_errors, error_keywords, register_values, dump_stack_context, pre_crash_events, cpu_context")


class CrashIssue(BaseModel):
    """知识库 issue"""
    source: str = Field(default="issue", description="数据来源标识")
    knowledge_id: str = Field(default_factory=lambda: f"issue-{_uid()}", description="问题唯一ID")
    fingerprints: list[str] = Field(default_factory=list, description="多指纹列表")

    bug_type: str = Field(default="", description="bug分类")
    bug_key: str = Field(default="", description="bug关键字")
    bug_summary: str = Field(default="", description="问题摘要")

    rip: str = Field(default="", description="崩溃指令指针")
    rip_function: str = Field(default="", description="RIP函数名")
    rip_offset: str = Field(default="", description="RIP偏移量")

    related_modules: list[str] = Field(default_factory=list, description="关联模块")
    call_trace_signature: list[str] = Field(default_factory=list, description="调用栈核心函数名")
    call_trace_text: str = Field(default="", description="调用栈原始文本")

    kernel_versions: list[str] = Field(default_factory=list, description="受影响内核版本")
    affected_components: list[str] = Field(default_factory=list, description="受影响组件")

    root_cause: str = Field(default="", description="根因分析")
    solution: str = Field(default="", description="解决方案")
    hotpatch: str = Field(default="", description="热补丁名称")
    history_wiki: str = Field(default="", description="wiki链接")

    match_score: float = Field(default=0.0, description="匹配分数 0-100")
    phenomenon: str = Field(default="", description="现象描述")
    source_url: str = Field(default="", description="来源链接")

    case_count: int = Field(default=0, description="关联案例数")
    first_seen: str = Field(default_factory=_utc_now, description="首次发现")
    last_seen: str = Field(default_factory=_utc_now, description="最近发现")

    match_reason: dict = Field(default_factory=dict, description="匹配原因: rip_match, call_trace_overlap, bug_type_match, module_match, kernel_version_match")
    error_keywords: list[str] = Field(default_factory=list, description="异常关键词，用于二次匹配")


class CrashCase(BaseModel):
    """案例记录"""
    source: str = Field(default="case", description="数据来源标识")
    case_id: str = Field(default_factory=lambda: f"case-{_uid()}", description="案例唯一ID")
    knowledge_id: str = Field(default="", description="关联的知识库ID")

    host_name: str = Field(default="", description="主机名")
    machine_model: str = Field(default="", description="服务器型号")
    kernel_version: str = Field(default="", description="内核版本")
    cpu_model: str = Field(default="", description="CPU型号")
    cpu_num: int = Field(default=0, description="CPU核数")
    memory_size: str = Field(default="", description="内存大小")
    uptime_seconds: int = Field(default=0, description="运行时长(秒)")
    vendor: str = Field(default="", description="厂商")
    modules: list[str] = Field(default_factory=list, description="内核模块列表")

    crash_time: str = Field(default="", description="宕机时间")
    crash_type: str = Field(default="", description="宕机类型")
    bug_type: str = Field(default="", description="bug分类")
    rip: str = Field(default="", description="崩溃指令指针")
    rip_function: str = Field(default="", description="RIP函数名")
    bug_key: str = Field(default="", description="bug关键字")
    bug: str = Field(default="", description="内核原始bug描述")
    call_trace: str = Field(default="", description="调用栈原始文本")
    call_trace_functions: list[str] = Field(default_factory=list, description="调用栈函数名列表")
    crash_cpu: int = Field(default=-1, description="崩溃CPU")
    crash_command: str = Field(default="", description="崩溃进程")
    related_modules: list[str] = Field(default_factory=list, description="关联模块")
    crash_log: str = Field(default="", description="崩溃日志片段")
    signature: str = Field(default="", description="签名")

    match_score: float = Field(default=0.0, description="匹配分数")
    match_method: str = Field(default="", description="匹配方法")

    created_at: str = Field(default_factory=_utc_now, description="创建时间")


class MatchResult(BaseModel):
    """匹配结果"""
    matched: bool = Field(default=False, description="是否匹配到已知问题")
    fingerprint_match: bool = Field(default=False, description="True=L1指纹, False=L2策略")

    knowledge: Optional[CrashIssue] = Field(default=None, description="匹配到的已知问题")
    similar_cases: list[CrashCase] = Field(default_factory=list, description="相似历史案例")
    current_case: Optional[CrashCase] = Field(default=None, description="本次宕机的案例记录")
    suggestions: list[str] = Field(default_factory=list, description="处理建议")

    missing_fields: list[str] = Field(default_factory=list, description="缺失字段: rip/call_trace/bug_key")


class ScoreDetails(BaseModel):
    """社区案例 / CrashIssue 打分明细."""

    kernel_version_score: float = Field(default=0.0)
    title_score: float = Field(default=0.0)
    content_score: float = Field(default=0.0)
    exact_token_score: float = Field(default=0.0)
    solution_score: float = Field(default=0.0)
    total: float = Field(default=0.0)
    reason: str = Field(default="", description="LLM/Agent 评分理由")


class CommunityCase(BaseModel):
    """社区案例 (openEuler/Linux 原始 JSON 格式)"""
    source: str = Field(default="", description="来源: OSClinic/Linux社区/openEuler社区")
    kb_id: str = Field(default="", description="所属知识库ID")
    json_id: str = Field(default="", description="RAG json_id")
    id: str = Field(default="", description="案例原始ID")
    type: str = Field(default="", description="类型 commit/issue/bug")
    title: str = Field(default="", description="标题")
    kernel_version: str = Field(default="", description="内核版本")
    phenomenon: str = Field(default="", description="现象")
    root_cause: str = Field(default="", description="根因")
    solution: str = Field(default="", description="解决方案")
    content: str = Field(default="", description="内容正文")
    source_file: str = Field(default="", description="原始链接")
    creattime: str = Field(default="", description="创建时间")
    score: float = Field(default=0.0, description="匹配分数 0-100")
    match_score: float = Field(default=0.0, description="匹配分数 0-1(shennong对齐)")
    match_level: str = Field(default="", description="L1/L2/L3")
    score_details: ScoreDetails = Field(default_factory=ScoreDetails, description="分数明细")

    match_reason: dict = Field(default_factory=dict, description="匹配原因: phenomenon_similarity, rip_consistency, module_match, commit_relevance, commit_summary")
    commit_diff: str = Field(default="", description="commit 的 diff 内容，用于相关性分析")


class CommunityMatchResult(BaseModel):
    """社区案例匹配结果"""
    matched: bool = Field(default=False, description="是否匹配到社区案例")
    stop_reason: str = Field(default="", description="停止检索原因")
    cases: list[CommunityCase] = Field(default_factory=list, description="top3 案例")
    total_candidates: int = Field(default=0, description="候选总数")
