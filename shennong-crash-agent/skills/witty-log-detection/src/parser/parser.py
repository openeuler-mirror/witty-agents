import os
import re
import tempfile
import subprocess
import asyncio
from datetime import datetime, timedelta
from typing import List, Optional
from src.service.embedding import Embedding
from src.parser.log_feature_loader import log_feature_class_mapping
from src.enum.log import LogTypeEnum, LogValueEnum
from src.schemas.log import LogModel
from src.service.ocr import OcrTool
from src.config.config import Config
import logging

# 加载全局配置
_config = Config().get_config()

logger = logging.getLogger(__name__)

class LogParser:
    """
    统一日志解析器：支持普通文本日志、二进制vmcore文件解析
    """
    # crash工具常用命令，用于提取vmcore的关键信息
    _CRASH_COMMANDS = [
        "sys",               # 系统基本信息
        "bt",                # 调用栈
        "ps",                # 进程列表
        "log",               # 内核日志
        "reg",               # 寄存器信息
        "vm",                # 内存信息
    ]

    @staticmethod
    def is_vmcore_file(file_path: str) -> bool:
        """判断是否为vmcore二进制文件"""
        if not os.path.exists(file_path):
            return False
        basename = os.path.basename(file_path).lower()
        # 首先检查文件名是否符合vmcore命名规则
        if not (basename == "vmcore" or basename.startswith("vmcore.")):
            return False
        # 再检查是否为ELF二进制文件或者非文本文件
        try:
            with open(file_path, "rb") as f:
                header = f.read(512)
                # 检查是否为ELF文件
                if header.startswith(b"\x7fELF"):
                    return True
                # 检查是否为二进制文件（包含空字节）
                if b"\x00" in header:
                    return True
                return False
        except Exception as e:
            logger.warning(f"检查vmcore文件失败: {e}")
            return False

    @staticmethod
    def _read_vmcore_dmesg(file_path: str) -> Optional[str]:
        """降级读取同目录下的vmcore-dmesg.txt"""
        dmesg_path = os.path.join(os.path.dirname(file_path), "vmcore-dmesg.txt")
        if os.path.exists(dmesg_path):
            logger.info(f"尝试读取同目录下的dmesg文件: {dmesg_path}")
            with open(dmesg_path, "r", encoding="utf-8", errors="ignore") as f:
                return f.read()
        return None

    @staticmethod
    def _dump_vmcore_to_text(file_path: str, vmlinux_path: Optional[str] = None) -> Optional[str]:
        """
        将二进制vmcore文件转储为文本格式
        :param file_path: vmcore文件路径
        :param vmlinux_path: 带调试信息的内核镜像路径，可选
        :return: 转储后的完整文本内容
        """
        cmd_file = None
        try:
            # 生成crash命令脚本
            with tempfile.NamedTemporaryFile(mode="w", suffix=".cmd", delete=False) as f:
                for cmd in LogParser._CRASH_COMMANDS:
                    f.write(f"{cmd}\n")
                f.write("quit\n")
                cmd_file = f.name

            # 构建并执行crash命令，执行失败直接进异常处理
            cmd = ["crash"]
            # 优先级：传入的vmlinux > 配置文件中的vmlinux路径 > 最小模式
            final_vmlinux_path = vmlinux_path or getattr(_config.vmcore, "vmlinux_path", None)
            if final_vmlinux_path and os.path.exists(final_vmlinux_path):
                cmd.append(final_vmlinux_path)
            else:
                cmd.append("--minimal")  # 无vmlinux时启用最小模式，尽量解析基础信息
            cmd.extend([file_path, "-i", cmd_file, "-s"])

            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=60,
                check=True  # 非0返回码直接抛异常
            )

            text_content = result.stdout

            # 开启保存功能时将转储文本写入本地
            if getattr(_config.vmcore, "save_parsed_text", False) and text_content:
                try:
                    # 确定保存目录：优先用配置的目录，否则用vmcore所在目录
                    save_dir = getattr(_config.vmcore, "save_path", "") or os.path.dirname(file_path)
                    if save_dir and not os.path.exists(save_dir):
                        os.makedirs(save_dir, exist_ok=True)
                    
                    # 生成文件名：原vmcore名 + _parsed + 时间戳 + 后缀
                    vmcore_name = os.path.basename(file_path)
                    from datetime import datetime
                    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                    suffix = getattr(_config.vmcore, "save_suffix", "txt").strip(".")
                    save_file_name = f"{vmcore_name}_parsed_{timestamp}.{suffix}"
                    save_full_path = os.path.join(save_dir, save_file_name)
                    
                    # 写入文件
                    with open(save_full_path, "w", encoding="utf-8", errors="ignore") as f:
                        f.write(text_content)
                    logger.info(f"vmcore转储文本已保存到: {save_full_path}")
                except Exception as save_e:
                    logger.warning(f"保存vmcore转储文本失败: {str(save_e)[:200]}")

            return text_content

        except Exception as e:
            logger.warning(f"vmcore转储失败: {str(e)[:200]}")
        finally:
            # 清理临时文件
            if cmd_file and os.path.exists(cmd_file):
                os.unlink(cmd_file)

        # 所有失败场景统一降级
        return LogParser._read_vmcore_dmesg(file_path)

    @staticmethod
    async def _parse_vmcore_file(file_path: str, vmlinux_path: Optional[str] = None, need_split_by_regex: bool = True) -> List[LogModel]:
        """
        内部方法：解析vmcore二进制文件，返回LogModel列表
        """
        # 先尝试转储为文本
        content = LogParser._dump_vmcore_to_text(file_path, vmlinux_path)
        if not content:
            # 如果转储失败，尝试作为文本文件读取（可能是已经导出的vmcore日志文本）
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
            except Exception as e:
                logger.error(f"读取vmcore文件失败: {e}")
                return []

        # 拆成行，交给统一的LogParser处理
        log_lines = content.splitlines()
        
        # 调用LogParser解析，复用kdump的所有feature配置
        log_models = await LogParser.parse_log_lines(
            log_lines=log_lines,
            file_path=file_path,
            need_split_by_regex=need_split_by_regex
        )

        # 所有vmcore日志默认标记为异常
        for log_model in log_models:
            log_model.log_type = LogTypeEnum.KDUMP.value
            log_model.is_anomalous = True
            
        return log_models

    @staticmethod
    def get_log_line_type(log_line: str) -> LogTypeEnum:
        """
        获取单行日志的类型
        """
        score_dict = {}
        for log_type in LogTypeEnum:
            if log_type in log_feature_class_mapping:
                keywrods_regex_and_scores = log_feature_class_mapping[
                    log_type
                ].keywords_regex_and_scores
                score = 0
                for keyword_regex, keyword_score in keywrods_regex_and_scores[
                    "normal"
                ].items():
                    if re.search(keyword_regex, log_line):
                        score += keyword_score
                for keyword_regex, keyword_score in keywrods_regex_and_scores[
                    "anomalous"
                ].items():
                    if re.search(keyword_regex, log_line):
                        score += keyword_score
                score_dict[log_type] = score
        # 如果所有的日志类型得分都为0，则默认为unknown类型
        if all(score == 0 for score in score_dict.values()):
            return LogTypeEnum.UNKNOWN
        # 获取得分最高的日志类型
        best_log_type = max(score_dict.items(), key=lambda x: x[1])[0]
        return best_log_type

    @staticmethod
    def read_log_file(file_path: str) -> list[str] | str:
        """
        读取日志文件，返回日志模型列表
        """
        log_lines = []
        image_end = re.compile(r".*\.(jpg|jpeg|png|bmp|gif)$", re.IGNORECASE)
        text_end = re.compile(r".*\.(log|txt|md|json|xml|csv)$", re.IGNORECASE)
        if re.match(image_end, file_path):
            log_lines = asyncio.run(OcrTool.image_to_text_list(file_path))
        elif re.match(text_end, file_path):
            with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                for line in f:
                    log_lines.append(line.strip())
                    
        return log_lines

    @staticmethod
    def _add_log_model_if_valid(
        log_models: list[LogModel],
        file_path: str,
        log_type: LogTypeEnum,
        offset: int,
        content: str,
    ) -> int:
        """
        辅助方法：如果内容有效（非空非空白），则添加到 log_models
        返回新的 offset（如果添加则 +1，否则不变）
        """
        stripped_content = content.strip()
        if stripped_content:
            log_models.append(
                LogModel(
                    file_path=file_path,
                    log_type=log_type,
                    offset=offset,
                    content=stripped_content,
                )
            )
            return offset + 1
        return offset

    @staticmethod
    async def mask_log_content(log_model: LogModel) -> str:
        """对日志内容进行脱敏处理"""
        # 这里实现日志内容脱敏的具体逻辑
        log_content = log_model.content
        log_type: LogTypeEnum = log_model.log_type or LogTypeEnum.UNKNOWN
        value_and_value_mask = [
            (LogValueEnum.IP, "<ip>"),
            (LogValueEnum.TIMESTAMP, "<timestamp>"),
            (LogValueEnum.LEVEL, "<level>"),
        ]
        masked_content = log_content[:]
        for log_value_enum, mask in value_and_value_mask:
            regex = log_feature_class_mapping[log_type].capture_patterns.get(
                log_value_enum.value, None
            )
            if regex is not None:
                masked_content = re.sub(regex, mask, masked_content)
        return masked_content

    @staticmethod
    async def get_log_templates(
        log_models: list[LogModel], batch_size: int = 8192, need_embedding: bool = False
    ) -> None:
        """获取日志模板"""
        # 这里实现获取日志模板的具体逻辑
        # logger.info(f"开始获取{len(log_models)}个日志模板")
        log_templates = []
        for i in range(0, len(log_models), batch_size):
            batch_log_models = log_models[i : i + batch_size]
            # logger.info(f"开始处理第{i+1}个批次，包含{len(batch_log_models)}个日志模型")
            masked_contents = await asyncio.gather(
                *[
                    LogParser.mask_log_content(log_model)
                    for log_model in batch_log_models
                ]
            )
            log_templates += masked_contents
        if need_embedding:
            # logger.info(f"开始对{len(log_templates)}个日志模板进行嵌入向量化")
            log_template_embeddings = await Embedding.vectorize_embedding(log_templates)
        
        for i in range(len(log_models)):
            # logger.info(f"开始处理第{i+1}个日志模型")
            log_models[i].template = log_templates[i]
            if need_embedding:
                log_models[i].template_vector = log_template_embeddings[i]
        # logger.info(f"获取到{len(log_models)}个日志模板")
    @staticmethod
    async def filter_log_models_not_in_time_range(
        log_models: list[LogModel],
        time_start: datetime | None,
        time_end: datetime | None,
    ) -> list[LogModel]:
        """获取日志模型的时间戳"""
        # 这里实现获取日志模型时间戳的具体逻辑
        log_models_in_time_range = []
        for log_model in log_models:
            start_time = None
            end_time = None
            log_type: LogTypeEnum = log_model.log_type or LogTypeEnum.UNKNOWN
            tiemstamp_regex = log_feature_class_mapping[log_type].capture_patterns.get(
                LogValueEnum.TIMESTAMP.value, None
            )
            if tiemstamp_regex is not None:
                timestamp = re.search(tiemstamp_regex, log_model.content)
                if timestamp is not None:
                    # 获取第一个匹配的时间戳字符串
                    timestamp_str = timestamp.group(0)
                    # 将时间戳字符串转换为datetime对象
                    time_format_list = [
                        # 基础标准格式（年-月-日 时:分:秒）
                        "%Y-%m-%d %H:%M:%S",
                        "%Y/%m/%d %H:%M:%S",
                        "%Y.%m.%d %H:%M:%S",
                        # 带毫秒/微秒的标准格式
                        "%Y-%m-%d %H:%M:%S.%f",
                        "%Y/%m/%d %H:%M:%S.%f",
                        "%Y.%m.%d %H:%M:%S.%f",
                        "%Y-%m-%d %H:%M:%S,%f",
                        "%Y/%m/%d %H:%M:%S,%f",
                        "%Y.%m.%d %H:%M:%S,%f",
                        # 带时区的格式（适配国际化日志）
                        "%Y-%m-%d %H:%M:%S%z",
                        "%Y-%m-%d %H:%M:%S.%f%z",
                        "%Y-%m-%dT%H:%M:%S%z",
                        "%Y-%m-%dT%H:%M:%S.%f%z",
                        # ISO8601格式（Go/Java/JS常用）
                        "%Y-%m-%dT%H:%M:%S",
                        "%Y-%m-%dT%H:%M:%S.%f",
                        # 月份缩写格式（Bash/系统日志常用）
                        "%b %d %H:%M:%S",
                        "%b %d %H:%M:%S.%f",
                        "%b %d %H:%M:%S,%f",
                        "%B %d %H:%M:%S",  # 月份全称（如January）
                        "%B %d %H:%M:%S.%f",
                        # 带年份的月份格式（Java日志常用）
                        "%b %d %Y %H:%M:%S",
                        "%b %d %Y %H:%M:%S.%f",
                        "%B %d %Y %H:%M:%S",
                        "%B %d %Y %H:%M:%S.%f",
                        # 美式日期格式（部分日志场景）
                        "%m/%d/%Y %H:%M:%S",
                        "%m/%d/%Y %H:%M:%S.%f",
                        # 内核/系统日志简化格式（dmesg/ftrace）
                        "%s.%f",  # Unix时间戳+小数（如1710000000.123456）
                        "%s",  # 纯Unix时间戳（10位数字）
                    ]
                    for time_fromat in time_format_list:
                        try:
                            timestamp_dt = datetime.strptime(timestamp_str, time_fromat)
                            start_time = (
                                min(start_time, timestamp_dt)
                                if start_time is not None
                                else timestamp_dt
                            )
                            end_time = (
                                max(end_time, timestamp_dt)
                                if end_time is not None
                                else timestamp_dt
                            )
                            break
                        except ValueError:
                            continue
            delta = timedelta(minutes=5)
            if (
                time_start is not None
                and start_time is not None
                and time_end is not None
                and start_time > time_end + delta
            ):
                continue
            if (
                time_end is not None
                and end_time is not None
                and time_start is not None
                and end_time < time_start - delta
            ):
                continue
            log_model.start_time = start_time
            log_model.end_time = end_time
            log_models_in_time_range.append(log_model)

        return log_models_in_time_range

    @staticmethod
    async def parse_log_lines(
        log_lines: list[str],
        file_path: str,
        need_split_by_regex: bool = False,
        time_start: datetime | None = None,
        time_end: datetime | None = None,
        chunk_size: int = 1024,
    ) -> list[LogModel]:
        """
        直接处理日志行列表，生成LogModel
        """
        log_models = []
        current = ""
        offset = 0
        if need_split_by_regex:
            index = 0
            while index < len(log_lines):
                log_line = log_lines[index]
                # 提取时间戳
                log_type = LogParser.get_log_line_type(log_line)
                # 判断是否为连续日志的开头，
                match_header_regex = None
                for header_regex in log_feature_class_mapping[log_type].mandatory:
                    if re.search(header_regex, log_line):
                        match_header_regex = header_regex
                        break
                if log_type != LogTypeEnum.UNKNOWN and match_header_regex is not None:
                    current = log_line + "\n"
                    index += 1
                    while index < len(log_lines):
                        is_continuous = False
                        for continuous_regex in log_feature_class_mapping[
                            log_type
                        ].mandatory[match_header_regex]:
                            if re.search(continuous_regex, log_lines[index]):
                                is_continuous = True
                                break
                        if is_continuous and len(current) < chunk_size:
                            current += log_lines[index] + "\n"
                            index += 1
                        else:
                            break
                    offset = LogParser._add_log_model_if_valid(
                        log_models,
                        file_path,
                        log_type,
                        offset,
                        current,
                    )
                else:
                    offset = LogParser._add_log_model_if_valid(
                        log_models,
                        file_path,
                        log_type,
                        offset,
                        log_line,
                    )
                    index += 1
        else:
            for log_line in log_lines:
                if len(current) + len(log_line) > chunk_size:
                    log_type_for_current = LogParser.get_log_line_type(current)
                    offset = LogParser._add_log_model_if_valid(
                        log_models,
                        file_path,
                        log_type_for_current,
                        offset,
                        current,
                    )
                    current = ""
                current += log_line + "\n"
            log_type_for_current = LogParser.get_log_line_type(current)
            offset = LogParser._add_log_model_if_valid(
                log_models,
                file_path,
                log_type_for_current,
                offset,
                current,
            )
        if time_start is not None or time_end is not None:
            log_models = await LogParser.filter_log_models_not_in_time_range(
                log_models, time_start, time_end
            )
        return log_models

    @staticmethod
    async def parse_log_file(
        file_path: str,
        need_split_by_regex: bool = False,
        time_start: datetime | None = None,
        time_end: datetime | None = None,
        chunk_size: int = 1024,
        vmlinux_path: str | None = None,
    ) -> list[LogModel]:
        # 自动识别vmcore二进制文件，优先走vmcore解析流程
        if LogParser.is_vmcore_file(file_path):
            return await LogParser._parse_vmcore_file(
                file_path=file_path,
                vmlinux_path=vmlinux_path,
                need_split_by_regex=need_split_by_regex
            )
        # 普通文本日志走原有流程
        log_lines = LogParser.read_log_file(file_path)
        return await LogParser.parse_log_lines(
            log_lines=log_lines,
            file_path=file_path,
            need_split_by_regex=need_split_by_regex,
            time_start=time_start,
            time_end=time_end,
            chunk_size=chunk_size
        )
