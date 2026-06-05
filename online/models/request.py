"""
请求相关数据库模型

对应 requests、field_extractions 和 agg_decisions 表。
"""

from typing import Any, Optional

from sqlalchemy import Boolean, Float, Integer, String, Text
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class Request(Base):
    """请求主表模型"""

    __tablename__ = "requests"

    trace_id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="请求唯一标识")
    doc_type: Mapped[str] = mapped_column(String(64), nullable=False, comment="单据类型")
    total_pages: Mapped[Optional[int]] = mapped_column(Integer, default=None, comment="总页数")
    final_fields: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSON, default=None, comment="最终字段结果"
    )
    warnings: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(
        JSON, default=None, comment="警告信息"
    )
    template_id: Mapped[Optional[str]] = mapped_column(
        String(64), default=None, comment="模板编号"
    )
    template_version: Mapped[Optional[str]] = mapped_column(
        String(32), default=None, comment="模板版本"
    )
    selected_weight: Mapped[Optional[int]] = mapped_column(
        Integer, default=None, comment="命中权重"
    )
    trace: Mapped[Optional[dict[str, Any]]] = mapped_column(
        JSON, default=None, comment="分流决策追踪"
    )
    created_at: Mapped[Optional[str]] = mapped_column(default=None, comment="创建时间")

    def __repr__(self) -> str:
        return f"<Request(trace_id={self.trace_id}, doc_type={self.doc_type})>"


class FieldExtraction(Base):
    """字段提取详情表模型"""

    __tablename__ = "field_extractions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    trace_id: Mapped[str] = mapped_column(String(64), nullable=False, comment="关联请求ID")
    page_num: Mapped[int] = mapped_column(Integer, nullable=False, comment="页码")
    field_name: Mapped[str] = mapped_column(String(64), nullable=False, comment="字段名称")
    extracted_value: Mapped[Optional[str]] = mapped_column(
        Text, default=None, comment="提取的值"
    )
    confidence: Mapped[Optional[float]] = mapped_column(Float, default=None, comment="置信度")
    raw_response: Mapped[Optional[str]] = mapped_column(
        Text, default=None, comment="VLM原始响应"
    )
    minio_path: Mapped[Optional[str]] = mapped_column(
        String(255), default=None, comment="MinIO图片路径"
    )
    created_at: Mapped[Optional[str]] = mapped_column(default=None, comment="创建时间")

    def __repr__(self) -> str:
        return f"<FieldExtraction(id={self.id}, trace_id={self.trace_id}, field_name={self.field_name})>"


class AggDecision(Base):
    """聚合决策表模型"""

    __tablename__ = "agg_decisions"

    trace_id: Mapped[str] = mapped_column(String(64), primary_key=True, comment="关联请求ID")
    field_name: Mapped[str] = mapped_column(String(64), primary_key=True, comment="字段名称")
    selected_page: Mapped[Optional[int]] = mapped_column(
        Integer, default=None, comment="选中的页码"
    )
    selected_value: Mapped[Optional[str]] = mapped_column(
        Text, default=None, comment="选中的值"
    )
    reason: Mapped[Optional[str]] = mapped_column(
        String(255), default=None, comment="聚合原因"
    )
    candidates: Mapped[Optional[list[dict[str, Any]]]] = mapped_column(
        JSON, default=None, comment="候选值列表"
    )

    def __repr__(self) -> str:
        return f"<AggDecision(trace_id={self.trace_id}, field_name={self.field_name})>"
