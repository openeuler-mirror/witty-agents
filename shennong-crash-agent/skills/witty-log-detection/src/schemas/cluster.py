from pydantic import BaseModel, Field
from src.schemas.log import LogModel


class ClusterModel(BaseModel):
    is_outlier: bool = Field(default=False, description="是否为离群点")
    cluster_center: list[float] = Field(..., description="聚类中心坐标")
    log_models: list[LogModel] = Field(
        ..., description="聚类中的日志模型列表")
