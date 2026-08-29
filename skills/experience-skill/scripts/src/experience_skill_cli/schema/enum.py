"""经验相关的枚举类型定义。"""

from enum import Enum


class ExperienceType(Enum):
    """经验类型：技能（SKILL）或百科（WIKI）。"""

    SKILL = "skill"
    WIKI = "wiki"


class ExperienceStatus(Enum):
    """经验状态：存在或已删除。"""

    EXISTED = "existed"
    DELETED = "deleted"
