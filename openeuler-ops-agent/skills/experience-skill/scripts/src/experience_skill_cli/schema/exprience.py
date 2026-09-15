"""经验数据模型定义。"""

from datetime import datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from experience_skill_cli.schema.enum import ExperienceStatus, ExperienceType


class Experience(BaseModel):
    """经验实体模型。"""

    id: str = Field(default_factory=lambda: str(uuid4()))
    type: ExperienceType = Field(default=ExperienceType.WIKI)
    name: str = Field(default="")
    description: str = Field(default="")
    keywords: list[str] = Field(default_factory=list)
    references: str = Field(default="")
    status: ExperienceStatus = Field(default=ExperienceStatus.EXISTED)
    is_hot: int = Field(default=0)
    source: str = Field(default="")
    created_at: str = Field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # noqa: DTZ005
    )
    updated_at: str = Field(
        default_factory=lambda: datetime.now().strftime("%Y-%m-%d %H:%M:%S"),  # noqa: DTZ005
    )
