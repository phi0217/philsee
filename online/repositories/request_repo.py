"""
请求仓库模块

封装 requests 表的数据库操作。
"""

import logging
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from online.models.request import Request

logger = logging.getLogger(__name__)


class RequestRepository:
    """请求仓库类"""

    def __init__(self, session: AsyncSession):
        """
        初始化请求仓库。

        Args:
            session: SQLAlchemy 异步会话。
        """
        self.session = session

    async def get_by_trace_id(self, trace_id: str) -> Optional[Request]:
        """
        根据 trace_id 获取请求记录。

        Args:
            trace_id: 请求唯一标识。

        Returns:
            Request 模型实例，不存在则返回 None。
        """
        query = select(Request).where(Request.trace_id == trace_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def insert(
        self,
        trace_id: str,
        doc_type: str,
        total_pages: Optional[int] = None,
        final_fields: Optional[dict[str, Any]] = None,
        warnings: Optional[list[dict[str, Any]]] = None,
        template_id: Optional[str] = None,
        template_version: Optional[str] = None,
        selected_weight: Optional[int] = None,
        trace: Optional[dict[str, Any]] = None,
    ) -> Request:
        """
        插入新的请求记录。

        Args:
            trace_id: 请求唯一标识。
            doc_type: 单据类型。
            total_pages: 总页数。
            final_fields: 最终字段结果。
            warnings: 警告列表。
            template_id: 使用的模板编号。
            template_version: 使用的模板版本。
            selected_weight: 命中模板版本的权重。
            trace: 分流决策追踪信息。

        Returns:
            新创建的 Request 实例。
        """
        request = Request(
            trace_id=trace_id,
            doc_type=doc_type,
            total_pages=total_pages,
            final_fields=final_fields,
            warnings=warnings,
            template_id=template_id,
            template_version=template_version,
            selected_weight=selected_weight,
            trace=trace,
        )
        self.session.add(request)
        await self.session.flush()
        return request

    async def update(
        self,
        trace_id: str,
        **kwargs: Any,
    ) -> Optional[Request]:
        """
        更新请求记录。

        Args:
            trace_id: 请求唯一标识。
            **kwargs: 要更新的字段。

        Returns:
            更新后的 Request 实例，不存在则返回 None。
        """
        request = await self.get_by_trace_id(trace_id)
        if request is None:
            return None

        for key, value in kwargs.items():
            if hasattr(request, key):
                setattr(request, key, value)

        await self.session.flush()
        return request

    async def delete(self, trace_id: str) -> bool:
        """
        删除请求记录。

        Args:
            trace_id: 请求唯一标识。

        Returns:
            成功删除返回 True，记录不存在返回 False。
        """
        request = await self.get_by_trace_id(trace_id)
        if request is None:
            return False

        await self.session.delete(request)
        await self.session.flush()
        return True

    async def list_by_doc_type(
        self,
        doc_type: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Request]:
        """
        按文档类型查询请求列表。

        Args:
            doc_type: 文档类型。
            limit: 返回数量限制。
            offset: 偏移量。

        Returns:
            请求列表。
        """
        query = (
            select(Request)
            .where(Request.doc_type == doc_type)
            .order_by(Request.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def list_by_template_id(
        self,
        template_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[Request]:
        """
        按模板编号查询请求列表。

        Args:
            template_id: 模板编号。
            limit: 返回数量限制。
            offset: 偏移量。

        Returns:
            请求列表。
        """
        query = (
            select(Request)
            .where(Request.template_id == template_id)
            .order_by(Request.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        result = await self.session.execute(query)
        return list(result.scalars().all())
