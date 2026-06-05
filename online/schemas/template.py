"""
模板生成相关的 Pydantic Schema

定义模板生成请求和响应的数据结构。
"""

from typing import Any, Optional

from pydantic import BaseModel, Field


class GenerateTemplateResponse(BaseModel):
    """模板生成响应"""

    template_id: str = Field(..., description="模板编号")
    template_version: str = Field(..., description="模板版本")
    doc_type: str = Field(..., description="文档类型")
    fields_config_id: int = Field(..., description="字段配置 ID")
    profile_config_id: int = Field(..., description="字段策略配置 ID")
    aggregation_config_id: int = Field(..., description="聚合规则配置 ID")
    message: str = Field(default="Template created successfully", description="消息")

    model_config = {
        "json_schema_extra": {
            "example": {
                "template_id": "invoice_default_20250605143000",
                "template_version": "v1.0.0",
                "doc_type": "invoice",
                "fields_config_id": 101,
                "profile_config_id": 102,
                "aggregation_config_id": 103,
                "message": "Template created successfully",
            }
        }
    }


class GenerateTemplateErrorResponse(BaseModel):
    """模板生成错误响应"""

    error: str = Field(..., description="错误信息")
    detail: Optional[str] = Field(None, description="详细错误信息")


class FieldDefinition(BaseModel):
    """字段定义"""

    type: str = Field(default="string", description="字段类型")
    description: Optional[str] = Field(None, description="字段描述")


class ProfileFieldConfig(BaseModel):
    """字段策略配置"""

    prompt_hint: Optional[str] = Field(None, description="提示词")
    pages: str | list[int] = Field(default="all", description="页码配置")


class AggregationRule(BaseModel):
    """聚合规则"""

    strategy: str = Field(default="first_non_null", description="聚合策略")


class FieldsConfig(BaseModel):
    """字段配置"""

    fields: dict[str, FieldDefinition] = Field(default_factory=dict, description="字段定义")


class ProfileConfig(BaseModel):
    """字段策略配置"""

    doc_type: str = Field(..., description="文档类型")
    fields: dict[str, ProfileFieldConfig] = Field(default_factory=dict, description="字段策略")


class AggregationConfig(BaseModel):
    """聚合规则配置"""

    default: AggregationRule = Field(default_factory=AggregationRule, description="默认规则")
    model_config = {"extra": "allow"}  # 允许额外字段作为特定字段规则
