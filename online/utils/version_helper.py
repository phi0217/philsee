"""
版本辅助函数模块

提供模板 ID 生成、版本号生成、配置版本检查和插入等功能。
"""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from online.models.config import ConfigVersion, ConfigTemplate

logger = logging.getLogger(__name__)


def generate_default_template_id(doc_type: str) -> str:
    """
    生成默认的模板 ID。

    格式：{doc_type}_default_{timestamp}
    其中 timestamp 为 %Y%m%d%H%M%S 格式。

    Args:
        doc_type: 文档类型（如 invoice, letter_of_credit）。

    Returns:
        str: 生成的模板 ID，如 invoice_default_20250605143000。
    """
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"{doc_type}_default_{timestamp}"


async def generate_template_version(session: AsyncSession, template_id: str, provided_version: Optional[str] = None) -> str:
    """
    生成模板版本号。

    若用户提供了版本号，直接使用。
    否则查询 config_templates 中该 template_id 下的最大版本，递增生成。

    递增规则：
    - 若已有 v1.0.0 则生成 v1.0.1
    - 若已有 v1.0.5 则生成 v1.0.6
    - 若无任何版本则使用 v1.0.0

    Args:
        session: SQLAlchemy 异步会话。
        template_id: 模板 ID。
        provided_version: 用户提供的版本号（可选）。

    Returns:
        str: 版本号字符串（如 v1.0.0）。
    """
    if provided_version:
        return provided_version

    try:
        # 查询该 template_id 下的所有版本
        query = select(ConfigTemplate.version).where(
            ConfigTemplate.template_id == template_id
        )
        result = await session.execute(query)
        versions = result.scalars().all()

        if not versions:
            return "v1.0.0"

        # 解析版本号并找到最大值
        max_major, max_minor, max_patch = 1, 0, 0

        for v in versions:
            try:
                # 解析版本号格式 v1.0.0
                if v.startswith("v"):
                    parts = v[1:].split(".")
                    if len(parts) == 3:
                        major, minor, patch = int(parts[0]), int(parts[1]), int(parts[2])
                        if (major > max_major or
                            (major == max_major and minor > max_minor) or
                            (major == max_major and minor == max_minor and patch > max_patch)):
                            max_major, max_minor, max_patch = major, minor, patch
            except (ValueError, IndexError):
                logger.warning(f"无法解析版本号: {v}，跳过")
                continue

        # 递增 patch 版本
        max_patch += 1
        return f"v{max_major}.{max_minor}.{max_patch}"

    except Exception as e:
        logger.error(f"生成模板版本失败: {e}")
        return "v1.0.0"


async def check_config_version_exists(
    session: AsyncSession,
    doc_type: str,
    config_type: str,
    version_tag: str,
) -> bool:
    """
    检查配置版本是否已存在。

    Args:
        session: SQLAlchemy 异步会话。
        doc_type: 文档类型。
        config_type: 配置类型（fields, profile, aggregation）。
        version_tag: 版本标签。

    Returns:
        bool: True 表示已存在，False 表示不存在。
    """
    try:
        query = select(ConfigVersion.id).where(
            ConfigVersion.doc_type == doc_type,
            ConfigVersion.config_type == config_type,
            ConfigVersion.version_tag == version_tag,
            ConfigVersion.is_deleted == False,  # noqa: E712
        )
        result = await session.execute(query)
        exists = result.scalar_one_or_none() is not None
        return exists

    except Exception as e:
        logger.error(f"检查配置版本失败: doc_type={doc_type}, config_type={config_type}, version_tag={version_tag}, error={e}")
        raise


async def insert_config_version(
    session: AsyncSession,
    doc_type: str,
    config_type: str,
    version_tag: str,
    content: dict,
    created_by: str = "system",
) -> int:
    """
    插入配置版本记录。

    Args:
        session: SQLAlchemy 异步会话。
        doc_type: 文档类型。
        config_type: 配置类型（fields, profile, aggregation）。
        version_tag: 版本标签。
        content: 配置内容（JSON 对象）。
        created_by: 创建者。

    Returns:
        int: 新插入记录的 ID。

    Raises:
        IntegrityError: 唯一约束冲突时抛出。
    """
    try:
        config = ConfigVersion(
            version_tag=version_tag,
            doc_type=doc_type,
            config_type=config_type,
            content=content,
            created_by=created_by,
            is_deleted=False,
        )
        session.add(config)
        await session.flush()
        await session.refresh(config)
        logger.info(
            f"配置版本插入成功: id={config.id}, doc_type={doc_type}, "
            f"config_type={config_type}, version_tag={version_tag}"
        )
        return config.id

    except Exception as e:
        logger.error(
            f"配置版本插入失败: doc_type={doc_type}, config_type={config_type}, "
            f"version_tag={version_tag}, error={e}"
        )
        raise


async def check_template_exists(
    session: AsyncSession,
    template_id: str,
    version: str,
) -> bool:
    """
    检查模板是否已存在。

    Args:
        session: SQLAlchemy 异步会话。
        template_id: 模板 ID。
        version: 版本号。

    Returns:
        bool: True 表示已存在，False 表示不存在。
    """
    try:
        query = select(ConfigTemplate.id).where(
            ConfigTemplate.template_id == template_id,
            ConfigTemplate.version == version,
        )
        result = await session.execute(query)
        exists = result.scalar_one_or_none() is not None
        return exists

    except Exception as e:
        logger.error(f"检查模板失败: template_id={template_id}, version={version}, error={e}")
        raise


async def insert_template(
    session: AsyncSession,
    template_id: str,
    version: str,
    doc_type: str,
    fields_config_id: int,
    profile_config_id: int,
    aggregation_config_id: int,
    description: str,
    pre_process: str = "",
    created_by: str = "system",
) -> int:
    """
    插入模板记录。

    Args:
        session: SQLAlchemy 异步会话。
        template_id: 模板 ID。
        version: 版本号。
        doc_type: 文档类型。
        fields_config_id: fields 配置 ID。
        profile_config_id: profile 配置 ID。
        aggregation_config_id: aggregation 配置 ID。
        description: 描述。
        pre_process: 前处理管道配置。
        created_by: 创建者。

    Returns:
        int: 新插入记录的 ID。

    Raises:
        IntegrityError: 唯一约束冲突时抛出。
    """
    try:
        template = ConfigTemplate(
            template_id=template_id,
            version=version,
            doc_type=doc_type,
            description=description,
            fields_config_id=fields_config_id,
            profile_config_id=profile_config_id,
            aggregation_config_id=aggregation_config_id,
            pre_process=pre_process,
            is_active=True,
            weight=100,
            created_by=created_by,
        )
        session.add(template)
        await session.flush()
        await session.refresh(template)
        logger.info(
            f"模板插入成功: id={template.id}, template_id={template_id}, "
            f"version={version}, doc_type={doc_type}"
        )
        return template.id

    except Exception as e:
        logger.error(
            f"模板插入失败: template_id={template_id}, version={version}, error={e}"
        )
        raise
