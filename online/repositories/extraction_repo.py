"""
提取记录仓库模块

封装 field_extractions 和 agg_decisions 表的数据库操作。
"""

import logging
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from online.models.request import FieldExtraction, AggDecision

logger = logging.getLogger(__name__)


class ExtractionRepository:
    """提取记录仓库类"""

    def __init__(self, session: AsyncSession):
        """
        初始化提取记录仓库。

        Args:
            session: SQLAlchemy 异步会话。
        """
        self.session = session

    # ==================== FieldExtraction 操作 ====================

    async def insert_field_extraction(
        self,
        trace_id: str,
        page_num: int,
        field_name: str,
        extracted_value: Optional[str] = None,
        confidence: Optional[float] = None,
        raw_response: Optional[str] = None,
        minio_path: Optional[str] = None,
    ) -> FieldExtraction:
        """
        插入单条字段提取记录。

        Args:
            trace_id: 请求唯一标识。
            page_num: 页码。
            field_name: 字段名称。
            extracted_value: 提取的值。
            confidence: 置信度。
            raw_response: 原始响应。
            minio_path: MinIO 图片路径。

        Returns:
            新创建的 FieldExtraction 实例。
        """
        extraction = FieldExtraction(
            trace_id=trace_id,
            page_num=page_num,
            field_name=field_name,
            extracted_value=extracted_value,
            confidence=confidence,
            raw_response=raw_response,
            minio_path=minio_path,
        )
        self.session.add(extraction)
        await self.session.flush()
        return extraction

    async def insert_field_extractions_batch(
        self,
        records: list[dict[str, Any]],
    ) -> int:
        """
        批量插入字段提取记录。

        Args:
            records: 记录字典列表，每个字典包含：
                - trace_id: 请求唯一标识
                - page_num: 页码
                - field_name: 字段名称
                - extracted_value: 提取的值
                - confidence: 置信度
                - raw_response: 原始响应
                - minio_path: MinIO 图片路径

        Returns:
            插入的记录数。
        """
        if not records:
            return 0

        extractions = [
            FieldExtraction(
                trace_id=r["trace_id"],
                page_num=r["page_num"],
                field_name=r["field_name"],
                extracted_value=r.get("extracted_value"),
                confidence=r.get("confidence"),
                raw_response=r.get("raw_response"),
                minio_path=r.get("minio_path"),
            )
            for r in records
        ]

        self.session.add_all(extractions)
        await self.session.flush()
        return len(extractions)

    async def get_by_trace_id(self, trace_id: str) -> list[FieldExtraction]:
        """
        根据 trace_id 获取所有字段提取记录。

        Args:
            trace_id: 请求唯一标识。

        Returns:
            字段提取记录列表。
        """
        query = (
            select(FieldExtraction)
            .where(FieldExtraction.trace_id == trace_id)
            .order_by(FieldExtraction.page_num, FieldExtraction.field_name)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_by_trace_and_page(
        self,
        trace_id: str,
        page_num: int,
    ) -> list[FieldExtraction]:
        """
        根据 trace_id 和页码获取字段提取记录。

        Args:
            trace_id: 请求唯一标识。
            page_num: 页码。

        Returns:
            字段提取记录列表。
        """
        query = (
            select(FieldExtraction)
            .where(FieldExtraction.trace_id == trace_id)
            .where(FieldExtraction.page_num == page_num)
            .order_by(FieldExtraction.field_name)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    # ==================== AggDecision 操作 ====================

    async def insert_agg_decision(
        self,
        trace_id: str,
        field_name: str,
        selected_page: Optional[int] = None,
        selected_value: Optional[str] = None,
        reason: Optional[str] = None,
        candidates: Optional[list[dict[str, Any]]] = None,
    ) -> AggDecision:
        """
        插入单条聚合决策记录。

        Args:
            trace_id: 请求唯一标识。
            field_name: 字段名称。
            selected_page: 选中的页码。
            selected_value: 选中的值。
            reason: 聚合原因。
            candidates: 候选值列表。

        Returns:
            新创建的 AggDecision 实例。
        """
        decision = AggDecision(
            trace_id=trace_id,
            field_name=field_name,
            selected_page=selected_page,
            selected_value=selected_value,
            reason=reason,
            candidates=candidates,
        )
        self.session.add(decision)
        await self.session.flush()
        return decision

    async def insert_agg_decisions_batch(
        self,
        records: list[dict[str, Any]],
    ) -> int:
        """
        批量插入聚合决策记录。

        Args:
            records: 记录字典列表，每个字典包含：
                - trace_id: 请求唯一标识
                - field_name: 字段名称
                - selected_page: 选中的页码
                - selected_value: 选中的值
                - reason: 聚合原因
                - candidates: 候选值列表

        Returns:
            插入的记录数。
        """
        if not records:
            return 0

        decisions = [
            AggDecision(
                trace_id=r["trace_id"],
                field_name=r["field_name"],
                selected_page=r.get("selected_page"),
                selected_value=r.get("selected_value"),
                reason=r.get("reason"),
                candidates=r.get("candidates"),
            )
            for r in records
        ]

        self.session.add_all(decisions)
        await self.session.flush()
        return len(decisions)

    async def get_decisions_by_trace_id(
        self,
        trace_id: str,
    ) -> list[AggDecision]:
        """
        根据 trace_id 获取所有聚合决策记录。

        Args:
            trace_id: 请求唯一标识。

        Returns:
            聚合决策记录列表。
        """
        query = (
            select(AggDecision)
            .where(AggDecision.trace_id == trace_id)
            .order_by(AggDecision.field_name)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_decision_by_field(
        self,
        trace_id: str,
        field_name: str,
    ) -> Optional[AggDecision]:
        """
        根据 trace_id 和字段名获取聚合决策记录。

        Args:
            trace_id: 请求唯一标识。
            field_name: 字段名称。

        Returns:
            聚合决策记录，不存在则返回 None。
        """
        query = select(AggDecision).where(
            AggDecision.trace_id == trace_id,
            AggDecision.field_name == field_name,
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()
