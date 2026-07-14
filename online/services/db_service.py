"""
数据库写入服务模块

将处理结果写入 MySQL 数据库，包括：
- requests: 请求主记录（包含模板和分流决策追踪信息）
- field_extractions: 每页每个字段的提取详情
- agg_decisions: 聚合决策记录

使用 Repository 层进行数据库操作。
"""

import json
import logging
from decimal import Decimal
from typing import Any, Optional

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from online.repositories.request_repo import RequestRepository
from online.repositories.extraction_repo import ExtractionRepository

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
    template_id: Optional[str] = None,
    template_version: Optional[str] = None,
    selected_weight: Optional[int] = None,
    resolve_trace: Optional[dict[str, Any]] = None,
) -> None:
    """
    将处理结果保存到数据库。

    分别写入 requests、field_extractions、agg_decisions 三个表。
    使用 Repository 层进行数据操作，保证一致性和可测试性。

    Args:
        session: SQLAlchemy 异步会话。
        trace_id: 请求唯一标识。
        doc_type: 单据类型。
        total_pages: 总页数。
        final_fields: 最终聚合后的字段字典。
        warnings: 警告列表。
        page_results: 所有页的提取结果。
        agg_decisions: 聚合决策字典。
        template_id: 使用的模板编号。
        template_version: 使用的模板版本。
        selected_weight: 命中模板版本的权重。
        resolve_trace: 分流决策追踪信息。

    Raises:
        DatabaseWriterError: 数据库写入失败时抛出。
    """
    request_repo = RequestRepository(session)
    extraction_repo = ExtractionRepository(session)

    logger.info(
        f"开始保存结果: trace_id={trace_id}, doc_type={doc_type}, "
        f"total_pages={total_pages}, template={template_id}@{template_version}"
    )

    try:
        # 1. 插入 requests 记录（使用 Repository）
        await request_repo.insert(
            trace_id=trace_id,
            doc_type=doc_type,
            total_pages=total_pages,
            final_fields=final_fields,
            warnings=warnings,
            template_id=template_id,
            template_version=template_version,
            selected_weight=selected_weight,
            trace=resolve_trace,
        )
        logger.info(f"requests 记录已插入: trace_id={trace_id}")

        # 2. 批量插入 field_extractions（使用 Repository）
        extraction_count = await _insert_field_extractions_batch(
            extraction_repo=extraction_repo,
            trace_id=trace_id,
            page_results=page_results,
        )
        logger.info(f"field_extractions 记录已插入: {extraction_count} 条")

        # 3. 插入 agg_decisions（使用 Repository）
        decision_count = await _insert_agg_decisions_batch(
            extraction_repo=extraction_repo,
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


async def _insert_field_extractions_batch(
    extraction_repo: ExtractionRepository,
    trace_id: str,
    page_results: list[list[dict[str, Any]]],
) -> int:
    """
    批量插入 field_extractions 记录。

    Args:
        extraction_repo: 提取记录仓库实例。
        trace_id: 请求唯一标识。
        page_results: 所有页的提取结果。

    Returns:
        int: 插入的记录数。
    """
    if not page_results:
        return 0

    records = []

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

            records.append({
                "trace_id": trace_id,
                "page_num": page_num,
                "field_name": field_name,
                "extracted_value": _value_to_db_string(value),
                "confidence": confidence,
                "raw_response": raw_response if raw_response else None,
                "minio_path": minio_path,
            })

    if not records:
        return 0

    return await extraction_repo.insert_field_extractions_batch(records)


async def _insert_agg_decisions_batch(
    extraction_repo: ExtractionRepository,
    trace_id: str,
    agg_decisions: dict[str, Any],
    final_fields: dict[str, Any],
) -> int:
    """
    批量插入 agg_decisions 记录。

    Args:
        extraction_repo: 提取记录仓库实例。
        trace_id: 请求唯一标识。
        agg_decisions: 聚合决策字典。
        final_fields: 最终字段字典（用于获取 selected_value）。

    Returns:
        int: 插入的记录数。
    """
    if not agg_decisions:
        return 0

    records = []

    for field_name, decision in agg_decisions.items():
        selected_page = decision.get("selected_page")
        reason = decision.get("reason", "")
        candidates = decision.get("candidates", [])
        selected_value = final_fields.get(field_name)

        records.append({
            "trace_id": trace_id,
            "field_name": field_name,
            "selected_page": selected_page,
            "selected_value": _value_to_db_string(selected_value),
            "reason": reason,
            "candidates": _convert_value_for_json(candidates),
        })

    if not records:
        return 0

    return await extraction_repo.insert_agg_decisions_batch(records)


async def create_tables(engine, dialect: str = "mysql") -> None:
    """
    创建数据库表（如果不存在）。

    注意：此函数仅创建基础表结构，完整的表结构请使用 sql/init_db.sql 初始化脚本。

    Args:
        engine: SQLAlchemy 异步引擎。
        dialect: 数据库类型 ("mysql" 或 "sqlite")。
    """
    if dialect == "sqlite":
        create_requests = """
        CREATE TABLE IF NOT EXISTS requests (
            trace_id VARCHAR(64) PRIMARY KEY,
            doc_type VARCHAR(64) NOT NULL,
            total_pages INT,
            final_fields TEXT,
            warnings TEXT,
            template_id VARCHAR(64),
            template_version VARCHAR(32),
            selected_weight INT,
            trace TEXT,
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

        create_config_versions = """
        CREATE TABLE IF NOT EXISTS config_versions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            version_tag VARCHAR(64) NOT NULL,
            doc_type VARCHAR(64) NOT NULL,
            config_type VARCHAR(32) NOT NULL,
            content TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by VARCHAR(64),
            is_deleted BOOLEAN DEFAULT FALSE
        )
        """

        create_config_templates = """
        CREATE TABLE IF NOT EXISTS config_templates (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            template_id VARCHAR(64) NOT NULL,
            version VARCHAR(32) NOT NULL,
            doc_type VARCHAR(64) NOT NULL,
            description TEXT,
            fields_config_id INT NOT NULL,
            profile_config_id INT NOT NULL,
            aggregation_config_id INT NOT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            weight INT NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by VARCHAR(64),
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_by VARCHAR(64)
        )
        """

        create_index = """
        CREATE INDEX IF NOT EXISTS idx_field_extractions
        ON field_extractions(trace_id, page_num)
        """
    else:
        create_requests = """
        CREATE TABLE IF NOT EXISTS requests (
            trace_id VARCHAR(64) PRIMARY KEY,
            doc_type VARCHAR(64) NOT NULL,
            total_pages INT,
            final_fields JSON,
            warnings JSON,
            template_id VARCHAR(64),
            template_version VARCHAR(32),
            selected_weight INT,
            trace JSON,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            INDEX idx_doc_type (doc_type),
            INDEX idx_template_id (template_id)
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

        create_config_versions = """
        CREATE TABLE IF NOT EXISTS config_versions (
            id INT PRIMARY KEY AUTO_INCREMENT,
            version_tag VARCHAR(64) NOT NULL,
            doc_type VARCHAR(64) NOT NULL,
            config_type ENUM('fields','profile','aggregation') NOT NULL,
            content JSON NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by VARCHAR(64),
            is_deleted BOOLEAN DEFAULT FALSE,
            UNIQUE KEY uk_unique (doc_type, config_type, version_tag)
        )
        """

        create_config_templates = """
        CREATE TABLE IF NOT EXISTS config_templates (
            id INT PRIMARY KEY AUTO_INCREMENT,
            template_id VARCHAR(64) NOT NULL,
            version VARCHAR(32) NOT NULL,
            doc_type VARCHAR(64) NOT NULL,
            description TEXT,
            fields_config_id INT NOT NULL,
            profile_config_id INT NOT NULL,
            aggregation_config_id INT NOT NULL,
            is_active BOOLEAN DEFAULT TRUE,
            weight INT NOT NULL DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            created_by VARCHAR(64),
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
            updated_by VARCHAR(64),
            UNIQUE KEY uk_template_version (template_id, version),
            KEY idx_doc_type (doc_type),
            KEY idx_active (template_id, is_active)
        )
        """

        create_index = None

    async with engine.begin() as conn:
        await conn.execute(text(create_config_versions))
        await conn.execute(text(create_config_templates))
        await conn.execute(text(create_requests))
        await conn.execute(text(create_field_extractions))
        await conn.execute(text(create_agg_decisions))
        if create_index:
            await conn.execute(text(create_index))

    logger.info("数据库表创建完成")