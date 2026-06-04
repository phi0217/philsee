"""
数据库写入模块

将处理结果写入 MySQL 数据库，包括：
- requests: 请求主记录
- field_extractions: 每页每个字段的提取详情
- agg_decisions: 聚合决策记录

使用异步 SQLAlchemy 引擎，支持批量插入以提高效率。
"""

import json
import logging
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)


class DatabaseWriterError(Exception):
    """数据库写入异常"""

    pass


def _convert_value_for_json(value: Any) -> Any:
    """
    将值转换为 JSON 可序列化类型。

    Args:
        value: 任意类型的值。

    Returns:
        Any: 可 JSON 序列化的值。
    """
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (list, dict)):
        # 递归处理列表和字典中的元素
        if isinstance(value, list):
            return [_convert_value_for_json(item) for item in value]
        else:
            return {k: _convert_value_for_json(v) for k, v in value.items()}
    return value


def _value_to_db_string(value: Any) -> str | None:
    """
    将值转换为数据库存储字符串。

    Args:
        value: 任意类型的值。

    Returns:
        str | None: 转换后的字符串，None 值返回 None。
    """
    if value is None:
        return None
    if isinstance(value, (list, dict)):
        return json.dumps(_convert_value_for_json(value), ensure_ascii=False)
    return str(value)


async def save_results(
    session: AsyncSession,
    trace_id: str,
    doc_type: str,
    total_pages: int,
    final_fields: dict[str, Any],
    warnings: list[dict[str, Any]],
    page_results: list[list[dict[str, Any]]],
    agg_decisions: dict[str, Any],
) -> None:
    """
    将处理结果保存到数据库。

    分别写入 requests、field_extractions、agg_decisions 三个表。
    如果任何步骤失败，将回滚事务并抛出异常。

    Args:
        session: SQLAlchemy 异步会话。
        trace_id: 请求唯一标识。
        doc_type: 单据类型。
        total_pages: 总页数。
        final_fields: 最终聚合后的字段字典。
        warnings: 警告列表。
        page_results: 所有页的提取结果。
        agg_decisions: 聚合决策字典。

    Raises:
        DatabaseWriterError: 数据库写入失败时抛出。
    """
    logger.info(
        f"开始保存结果: trace_id={trace_id}, doc_type={doc_type}, "
        f"total_pages={total_pages}"
    )

    try:
        # 1. 插入 requests 记录
        await _insert_request(
            session=session,
            trace_id=trace_id,
            doc_type=doc_type,
            total_pages=total_pages,
            final_fields=final_fields,
            warnings=warnings,
        )
        logger.info(f"requests 记录已插入: trace_id={trace_id}")

        # 2. 批量插入 field_extractions
        extraction_count = await _insert_field_extractions(
            session=session,
            trace_id=trace_id,
            page_results=page_results,
        )
        logger.info(f"field_extractions 记录已插入: {extraction_count} 条")

        # 3. 插入 agg_decisions
        decision_count = await _insert_agg_decisions(
            session=session,
            trace_id=trace_id,
            agg_decisions=agg_decisions,
            final_fields=final_fields,
        )
        logger.info(f"agg_decisions 记录已插入: {decision_count} 条")

        # 4. 提交事务
        await session.commit()
        logger.info(f"结果保存成功: trace_id={trace_id}")

    except Exception as e:
        await session.rollback()
        error_msg = f"数据库写入失败: trace_id={trace_id}, error={e}"
        logger.error(error_msg)
        raise DatabaseWriterError(error_msg) from e


async def _insert_request(
    session: AsyncSession,
    trace_id: str,
    doc_type: str,
    total_pages: int,
    final_fields: dict[str, Any],
    warnings: list[dict[str, Any]],
) -> None:
    """
    插入 requests 记录。

    Args:
        session: SQLAlchemy 异步会话。
        trace_id: 请求唯一标识。
        doc_type: 单据类型。
        total_pages: 总页数。
        final_fields: 最终字段字典。
        warnings: 警告列表。
    """
    final_fields_json = json.dumps(
        _convert_value_for_json(final_fields), ensure_ascii=False
    )
    warnings_json = json.dumps(warnings, ensure_ascii=False)

    sql = text(
        """
        INSERT INTO requests (trace_id, doc_type, total_pages, final_fields, warnings)
        VALUES (:trace_id, :doc_type, :total_pages, :final_fields, :warnings)
        """
    )

    await session.execute(
        sql,
        {
            "trace_id": trace_id,
            "doc_type": doc_type,
            "total_pages": total_pages,
            "final_fields": final_fields_json,
            "warnings": warnings_json,
        },
    )


async def _insert_field_extractions(
    session: AsyncSession,
    trace_id: str,
    page_results: list[list[dict[str, Any]]],
) -> int:
    """
    批量插入 field_extractions 记录。

    Args:
        session: SQLAlchemy 异步会话。
        trace_id: 请求唯一标识。
        page_results: 所有页的提取结果。

    Returns:
        int: 插入的记录数。
    """
    if not page_results:
        return 0

    values_list = []

    for page_result in page_results:
        for field_result in page_result:
            field_name = field_result.get("field_name")
            page_num = field_result.get("page")
            value = field_result.get("value")
            confidence = field_result.get("confidence", 0.0)
            raw_response = field_result.get("raw_response", "")
            minio_path = field_result.get("minio_path")

            if field_name is None or page_num is None:
                logger.warning(f"字段结果缺少必要字段，跳过: {field_result}")
                continue

            values_list.append({
                "trace_id": trace_id,
                "page_num": page_num,
                "field_name": field_name,
                "extracted_value": _value_to_db_string(value),
                "confidence": confidence,
                "raw_response": raw_response if raw_response else None,
                "minio_path": minio_path,
            })

    if not values_list:
        return 0

    sql = text(
        """
        INSERT INTO field_extractions
        (trace_id, page_num, field_name, extracted_value, confidence, raw_response, minio_path)
        VALUES
        (:trace_id, :page_num, :field_name, :extracted_value, :confidence, :raw_response, :minio_path)
        """
    )

    await session.execute(sql, values_list)

    return len(values_list)


async def _insert_agg_decisions(
    session: AsyncSession,
    trace_id: str,
    agg_decisions: dict[str, Any],
    final_fields: dict[str, Any],
) -> int:
    """
    插入 agg_decisions 记录。

    Args:
        session: SQLAlchemy 异步会话。
        trace_id: 请求唯一标识。
        agg_decisions: 聚合决策字典。
        final_fields: 最终字段字典（用于获取 selected_value）。

    Returns:
        int: 插入的记录数。
    """
    if not agg_decisions:
        return 0

    values_list = []

    for field_name, decision in agg_decisions.items():
        selected_page = decision.get("selected_page")
        reason = decision.get("reason", "")
        candidates = decision.get("candidates", [])

        # 获取最终值
        selected_value = final_fields.get(field_name)

        # 转换 candidates 为 JSON
        candidates_json = json.dumps(
            _convert_value_for_json(candidates), ensure_ascii=False
        )

        values_list.append({
            "trace_id": trace_id,
            "field_name": field_name,
            "selected_page": selected_page,
            "selected_value": _value_to_db_string(selected_value),
            "reason": reason,
            "candidates": candidates_json,
        })

    if not values_list:
        return 0

    sql = text(
        """
        INSERT INTO agg_decisions
        (trace_id, field_name, selected_page, selected_value, reason, candidates)
        VALUES
        (:trace_id, :field_name, :selected_page, :selected_value, :reason, :candidates)
        """
    )

    await session.execute(sql, values_list)

    return len(values_list)


async def create_tables(engine, dialect: str = "mysql") -> None:
    """
    创建数据库表（如果不存在）。

    Args:
        engine: SQLAlchemy 异步引擎。
        dialect: 数据库类型 ("mysql" 或 "sqlite")。
    """
    if dialect == "sqlite":
        # SQLite 语法
        create_requests = """
        CREATE TABLE IF NOT EXISTS requests (
            trace_id VARCHAR(64) PRIMARY KEY,
            doc_type VARCHAR(32) NOT NULL,
            total_pages INT,
            final_fields TEXT,
            warnings TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """

        create_field_extractions = """
        CREATE TABLE IF NOT EXISTS field_extractions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            trace_id VARCHAR(64) NOT NULL,
            page_num INT NOT NULL,
            field_name VARCHAR(64) NOT NULL,
            extracted_value TEXT,
            confidence FLOAT,
            raw_response TEXT,
            minio_path VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """

        create_agg_decisions = """
        CREATE TABLE IF NOT EXISTS agg_decisions (
            trace_id VARCHAR(64) NOT NULL,
            field_name VARCHAR(64) NOT NULL,
            selected_page INT,
            selected_value TEXT,
            reason VARCHAR(255),
            candidates TEXT,
            PRIMARY KEY(trace_id, field_name)
        )
        """

        create_index = """
        CREATE INDEX IF NOT EXISTS idx_field_extractions
        ON field_extractions(trace_id, page_num)
        """
    else:
        # MySQL 语法
        create_requests = """
        CREATE TABLE IF NOT EXISTS requests (
            trace_id VARCHAR(64) PRIMARY KEY,
            doc_type VARCHAR(32) NOT NULL,
            total_pages INT,
            final_fields JSON,
            warnings JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """

        create_field_extractions = """
        CREATE TABLE IF NOT EXISTS field_extractions (
            id BIGINT AUTO_INCREMENT PRIMARY KEY,
            trace_id VARCHAR(64) NOT NULL,
            page_num INT NOT NULL,
            field_name VARCHAR(64) NOT NULL,
            extracted_value TEXT,
            confidence FLOAT,
            raw_response TEXT,
            minio_path VARCHAR(255),
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX(trace_id, page_num)
        )
        """

        create_agg_decisions = """
        CREATE TABLE IF NOT EXISTS agg_decisions (
            trace_id VARCHAR(64) NOT NULL,
            field_name VARCHAR(64) NOT NULL,
            selected_page INT,
            selected_value TEXT,
            reason VARCHAR(255),
            candidates JSON,
            PRIMARY KEY(trace_id, field_name)
        )
        """

        create_index = None

    async with engine.begin() as conn:
        await conn.execute(text(create_requests))
        await conn.execute(text(create_field_extractions))
        await conn.execute(text(create_agg_decisions))
        if create_index:
            await conn.execute(text(create_index))

    logger.info("数据库表创建完成")
