from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field


class QueryResult(BaseModel):
    columns: list[str] = Field(default_factory=list)
    rows: list[list[Any]] = Field(default_factory=list)
    row_count: int = 0
    raw: Any = None
    latency_ms: float = 0.0
    warnings: list[str] = Field(default_factory=list)
    mode: str = ""  # sql | dsl | stub
    query: str | dict[str, Any] | None = None


class SchemaField(BaseModel):
    name: str
    type: str = "text"
    description: str = ""


class SchemaIndex(BaseModel):
    name: str
    fields: list[SchemaField] = Field(default_factory=list)


class SchemaSummary(BaseModel):
    indexes: list[SchemaIndex] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)


class PipelineStep(BaseModel):
    name: str
    status: str = "pending"  # pending|running|done|error|skipped
    message: str = ""
    detail: Any = None


class PipelineResult(BaseModel):
    query: str
    generated_query: str | dict[str, Any] | None = None
    mode: str = ""
    result: Optional[QueryResult] = None
    rules: list[dict[str, Any]] = Field(default_factory=list)
    steps: list[PipelineStep] = Field(default_factory=list)
    error: Optional[str] = None
    need_clarify: bool = False
    clarify_question: Optional[str] = None
