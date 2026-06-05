"""
配置相关数据库模型

对应 config_versions 和 config_templates 表。
"""

from typing import Optional

from sqlalchemy import JSON, Boolean, Integer, String, Text
from sqlalchemy.dialects.mysql import ENUM
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class ConfigVersion(Base):
    """配置版本表模型（无 is_active 字段）"""

    __tablename__ = "config_versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    version_tag: Mapped[str] = mapped_column(String(64), nullable=False, comment="版本标识")
    doc_type: Mapped[str] = mapped_column(String(64), nullable=False, comment="文档类型")
    config_type: Mapped[str] = mapped_column(
        ENUM("fields", "profile", "aggregation"),
        nullable=False,
        comment="配置类型",
    )
    content: Mapped[dict] = mapped_column(JSON, nullable=False, comment="配置内容")
    created_at: Mapped[Optional[str]] = mapped_column(default=None, comment="创建时间")
    created_by: Mapped[Optional[str]] = mapped_column(String(64), default=None, comment="创建人")
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, comment="是否删除")

    def __repr__(self) -> str:
        return f"<ConfigVersion(id={self.id}, version_tag={self.version_tag}, config_type={self.config_type})>"


class ConfigTemplate(Base):
    """配置模板表模型"""

    __tablename__ = "config_templates"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    template_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="模板编号")
    version: Mapped[str] = mapped_column(String(32), nullable=False, comment="模板版本")
    doc_type: Mapped[str] = mapped_column(String(64), nullable=False, comment="文档类型")
    description: Mapped[Optional[str]] = mapped_column(Text, default=None, comment="模板说明")
    fields_config_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="字段配置ID")
    profile_config_id: Mapped[int] = mapped_column(Integer, nullable=False, comment="字段策略配置ID")
    aggregation_config_id: Mapped[int] = mapped_column(
        Integer, nullable=False, comment="聚合规则配置ID"
    )
    pre_process: Mapped[Optional[str]] = mapped_column(
        String(255), default="", comment="前处理管道"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, comment="是否启用")
    weight: Mapped[int] = mapped_column(Integer, nullable=False, default=0, comment="分流权重")
    created_at: Mapped[Optional[str]] = mapped_column(default=None, comment="创建时间")
    created_by: Mapped[Optional[str]] = mapped_column(String(64), default=None, comment="创建人")
    updated_at: Mapped[Optional[str]] = mapped_column(default=None, comment="更新时间")
    updated_by: Mapped[Optional[str]] = mapped_column(String(64), default=None, comment="更新人")

    def __repr__(self) -> str:
        return f"<ConfigTemplate(id={self.id}, template_id={self.template_id}, version={self.version})>"
