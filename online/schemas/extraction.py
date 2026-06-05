"""
文档解析相关的 Pydantic Schema

定义解析请求和响应的数据结构。
"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class FieldResult(BaseModel):
    """字段提取结果"""

    field_name: str = Field(..., description="字段名称")
    value: Optional[Any] = Field(None, description="提取的值")
    confidence: float = Field(0.0, ge=0.0, le=1.0, description="置信度")
    raw_response: Optional[str] = Field(None, description="原始响应")


class PageResult(BaseModel):
    """单页提取结果"""

    page: int = Field(..., ge=1, description="页码")
    fields: list[FieldResult] = Field(default_factory=list, description="字段结果列表")


class ParseRequest(BaseModel):
    """解析请求参数"""

    doc_type: Optional[str] = Field(None, description="单据类型")
    template_id: Optional[str] = Field(None, description="模板编号")

    model_config = {
        "json_schema_extra": {
            "example": {
                "doc_type": "invoice",
                "template_id": "invoice_extraction",
            }
        }
    }


class ParseResponse(BaseModel):
    """解析响应"""

    trace_id: str = Field(..., description="请求唯一标识")
    fields: dict[str, Any] = Field(default_factory=dict, description="最终字段结果")
    warnings: list[dict[str, Any]] = Field(default_factory=list, description="警告信息")
    template: dict[str, Any] = Field(default_factory=dict, description="使用的模板信息")
    elapsed: float = Field(..., description="处理耗时（秒）")

    model_config = {
        "json_schema_extra": {
            "example": {
                "trace_id": "abc123def456",
                "fields": {"amount": 1000.0, "currency": "USD"},
                "warnings": [],
                "template": {"template_id": "invoice_extraction", "version": "v1.0.0"},
                "elapsed": 2.5,
            }
        }
    }


class ParseErrorResponse(BaseModel):
    """解析错误响应"""

    trace_id: Optional[str] = Field(None, description="请求唯一标识")
    error: str = Field(..., description="错误信息")


class AggDecisionDetail(BaseModel):
    """聚合决策详情"""

    selected_page: Optional[int] = Field(None, description="选中的页码")
    reason: str = Field(..., description="聚合原因")
    candidates: list[dict[str, Any]] = Field(default_factory=list, description="候选值列表")


class ExtractionDetail(BaseModel):
    """提取详情"""

    trace_id: str = Field(..., description="请求唯一标识")
    doc_type: str = Field(..., description="单据类型")
    total_pages: int = Field(..., description="总页数")
    final_fields: dict[str, Any] = Field(default_factory=dict, description="最终字段结果")
    template_id: Optional[str] = Field(None, description="使用的模板编号")
    template_version: Optional[str] = Field(None, description="使用的模板版本")
    field_extractions: list[dict[str, Any]] = Field(default_factory=list, description="字段提取详情")
    agg_decisions: dict[str, AggDecisionDetail] = Field(default_factory=dict, description="聚合决策详情")
