"""
配置相关的 Pydantic Schema

定义配置版本和模板的数据结构。
"""

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class ConfigVersionBase(BaseModel):
    """配置版本基础模型"""

    version_tag: str = Field(..., description="版本标识")
    doc_type: str = Field(..., description="文档类型")
    config_type: str = Field(..., description="配置类型")
    content: dict[str, Any] = Field(..., description="配置内容")


class ConfigVersionCreate(ConfigVersionBase):
    """创建配置版本请求"""

    created_by: Optional[str] = Field(None, description="创建人")


class ConfigVersionResponse(ConfigVersionBase):
    """配置版本响应"""

    id: int = Field(..., description="配置 ID")
    created_at: Optional[str] = Field(None, description="创建时间")
    created_by: Optional[str] = Field(None, description="创建人")
    is_deleted: bool = Field(default=False, description="是否删除")

    model_config = {"from_attributes": True}


class ConfigTemplateBase(BaseModel):
    """配置模板基础模型"""

    template_id: str = Field(..., description="模板编号")
    version: str = Field(..., description="模板版本")
    doc_type: str = Field(..., description="文档类型")
    description: Optional[str] = Field(None, description="模板说明")
    fields_config_id: int = Field(..., description="字段配置 ID")
    profile_config_id: int = Field(..., description="字段策略配置 ID")
    aggregation_config_id: int = Field(..., description="聚合规则配置 ID")
    pre_process: Optional[str] = Field("", description="前处理管道")
    is_active: bool = Field(default=True, description="是否启用")
    weight: int = Field(default=0, ge=0, le=100, description="分流权重")


class ConfigTemplateCreate(ConfigTemplateBase):
    """创建配置模板请求"""

    created_by: Optional[str] = Field(None, description="创建人")


class ConfigTemplateResponse(ConfigTemplateBase):
    """配置模板响应"""

    id: int = Field(..., description="模板 ID")
    created_at: Optional[str] = Field(None, description="创建时间")
    created_by: Optional[str] = Field(None, description="创建人")
    updated_at: Optional[str] = Field(None, description="更新时间")
    updated_by: Optional[str] = Field(None, description="更新人")

    model_config = {"from_attributes": True}


class ConfigTemplateListResponse(BaseModel):
    """模板列表响应"""

    templates: list[ConfigTemplateResponse] = Field(default_factory=list, description="模板列表")
    total: int = Field(..., description="总数")


class ResolveTrace(BaseModel):
    """分流决策追踪信息"""

    candidates: list[dict[str, Any]] = Field(default_factory=list, description="候选版本列表")
    weights: list[int] = Field(default_factory=list, description="权重列表")
    total_weight: int = Field(default=0, description="权重总和")
    random_value: int = Field(default=0, description="随机值")
    selected_index: int = Field(default=0, description="选中索引")
    selected_version: str = Field(..., description="选中版本")
    warning: Optional[str] = Field(None, description="警告信息")
    doc_type: Optional[str] = Field(None, description="文档类型")
    requested_template_id: Optional[str] = Field(None, description="请求的模板编号")
    resolved_template_id: Optional[str] = Field(None, description="解析后的模板编号")
    fallback_used: bool = Field(default=False, description="是否使用回退")


class LoadedConfig(BaseModel):
    """加载的配置"""

    fields_schema: dict[str, Any] = Field(default_factory=dict, description="字段定义")
    profile: dict[str, Any] = Field(default_factory=dict, description="字段策略")
    agg_rules: dict[str, Any] = Field(default_factory=dict, description="聚合规则")
    template: dict[str, Any] = Field(default_factory=dict, description="模板信息")
    trace: ResolveTrace = Field(..., description="分流决策追踪")
