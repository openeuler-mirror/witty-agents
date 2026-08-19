from enum import Enum


class ProviderEnum(str, Enum):
    OPENAPI = "openai"
    ASCENDING = "ascending"
    SILICONFLOW = "siliconflow"
    BAILIAN = "bailian"
