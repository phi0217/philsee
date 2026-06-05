"""
配置服务模块

提供配置加载、模板选择、分流决策等功能。
"""

import logging
import random
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from online.models.config import ConfigVersion, ConfigTemplate

logger = logging.getLogger(__name__)


class ConfigLoadError(Exception):
    """配置加载异常"""

    pass


# 默认的 doc_type 到 template_id 映射
# 可通过环境变量或配置文件覆盖
DEFAULT_TEMPLATE_MAP = {
    "letter_of_credit": "lc_extraction",
    "invoice": "invoice_extraction",
}


async def get_config_by_id(session: AsyncSession, config_id: int) -> dict[str, Any]:
    """
    根据 config_versions.id 获取配置内容。

    Args:
        session: SQLAlchemy 异步会话。
        config_id: config_versions 表的主键 ID。

    Returns:
        dict: 配置内容（content 字段的 Python 对象）。

    Raises:
        ConfigLoadError: 配置不存在或已删除时抛出。
    """
    try:
        query = select(ConfigVersion).where(
            ConfigVersion.id == config_id,
            ConfigVersion.is_deleted == False,  # noqa: E712
        )
        result = await session.execute(query)
        config = result.scalar_one_or_none()

        if config is None:
            raise ConfigLoadError(f"配置不存在: id={config_id}")

        return config.content

    except ConfigLoadError:
        raise
    except Exception as e:
        error_msg = f"获取配置失败: id={config_id}, error={e}"
        logger.error(error_msg)
        raise ConfigLoadError(error_msg) from e


async def get_active_templates(
    session: AsyncSession,
    template_id: Optional[str] = None,
    doc_type: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    获取符合条件的激活模板列表。

    Args:
        session: SQLAlchemy 异步会话。
        template_id: 可选，模板编号筛选。
        doc_type: 可选，文档类型筛选。

    Returns:
        list[dict]: 激活的模板记录列表（is_active=True）。
    """
    try:
        query = select(ConfigTemplate).where(ConfigTemplate.is_active == True)  # noqa: E712

        if template_id:
            query = query.where(ConfigTemplate.template_id == template_id)
        if doc_type:
            query = query.where(ConfigTemplate.doc_type == doc_type)

        result = await session.execute(query)
        templates = result.scalars().all()

        return [
            {
                "id": t.id,
                "template_id": t.template_id,
                "version": t.version,
                "doc_type": t.doc_type,
                "description": t.description,
                "fields_config_id": t.fields_config_id,
                "profile_config_id": t.profile_config_id,
                "aggregation_config_id": t.aggregation_config_id,
                "pre_process": t.pre_process or "",
                "weight": t.weight,
            }
            for t in templates
        ]

    except Exception as e:
        error_msg = f"获取激活模板失败: template_id={template_id}, doc_type={doc_type}, error={e}"
        logger.error(error_msg)
        raise ConfigLoadError(error_msg) from e


async def select_template(
    session: AsyncSession,
    template_id: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    根据权重随机选择一个模板版本。

    从指定 template_id 的所有激活版本中，按权重随机选择一个。
    返回选中的模板记录和分流决策追踪信息。

    Args:
        session: SQLAlchemy 异步会话。
        template_id: 模板编号。

    Returns:
        tuple[dict, dict]: (模板记录, trace_dict)
            trace_dict 包含:
            - candidates: 所有候选版本列表
            - weights: 各版本权重列表
            - total_weight: 权重总和
            - random_value: 随机生成的值
            - selected_index: 选中的索引
            - selected_version: 选中的版本号
            - warning: 警告信息（如果权重和不为100）

    Raises:
        ConfigLoadError: 没有激活的模板版本时抛出。
    """
    # 获取所有激活版本
    templates = await get_active_templates(session, template_id=template_id)

    if not templates:
        raise ConfigLoadError(f"没有激活的模板版本: template_id={template_id}")

    # 构建追踪信息
    candidates = [
        {"version": t["version"], "weight": t["weight"], "id": t["id"]}
        for t in templates
    ]
    weights = [t["weight"] for t in templates]
    total_weight = sum(weights)

    # 权重校验警告
    warning = None
    if total_weight != 100:
        warning = f"权重总和 ({total_weight}) 不等于 100，将按实际比例分配"

    # 如果总权重为 0，均等分配
    if total_weight == 0:
        selected_index = random.randint(0, len(templates) - 1)
        random_value = 0
    else:
        # 加权随机选择
        random_value = random.randint(1, total_weight)
        cumulative = 0
        selected_index = 0

        for i, w in enumerate(weights):
            cumulative += w
            if random_value <= cumulative:
                selected_index = i
                break

    selected_template = templates[selected_index]

    trace = {
        "candidates": candidates,
        "weights": weights,
        "total_weight": total_weight,
        "random_value": random_value,
        "selected_index": selected_index,
        "selected_version": selected_template["version"],
        "warning": warning,
    }

    logger.info(
        f"模板选择: template_id={template_id}, "
        f"selected_version={selected_template['version']}, "
        f"weight={selected_template['weight']}"
    )

    return selected_template, trace


async def resolve_template(
    session: AsyncSession,
    doc_type: Optional[str] = None,
    force_template_id: Optional[str] = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    解析请求参数，确定最终使用的模板。

    支持两种方式：
    1. 直接指定 template_id
    2. 通过 doc_type 映射到默认 template_id

    Args:
        session: SQLAlchemy 异步会话。
        doc_type: 文档类型（如 "letter_of_credit"）。
        force_template_id: 强制指定的模板编号（优先级更高）。

    Returns:
        tuple[dict, dict]: (模板记录, trace_dict)

    Raises:
        ConfigLoadError: 无法确定模板时抛出。
    """
    template_id = None
    fallback_used = False

    # 优先使用强制指定的 template_id
    if force_template_id:
        template_id = force_template_id
    elif doc_type:
        # 通过 doc_type 映射到默认 template_id
        template_id = DEFAULT_TEMPLATE_MAP.get(doc_type)
        if template_id is None:
            # 尝试查找该 doc_type 的任意激活模板
            templates = await get_active_templates(session, doc_type=doc_type)
            if templates:
                # 按 template_id 分组，选择第一个
                template_id = templates[0]["template_id"]
                fallback_used = True
                logger.warning(
                    f"doc_type={doc_type} 没有默认模板映射，使用第一个激活模板: {template_id}"
                )
            else:
                raise ConfigLoadError(
                    f"找不到 doc_type={doc_type} 的激活模板，请检查配置或提供 template_id"
                )
    else:
        raise ConfigLoadError("必须提供 doc_type 或 template_id 参数")

    # 根据权重选择模板版本
    template, select_trace = await select_template(session, template_id)

    # 合并追踪信息
    trace = {
        **select_trace,
        "doc_type": doc_type,
        "requested_template_id": force_template_id,
        "resolved_template_id": template_id,
        "fallback_used": fallback_used,
    }

    return template, trace


async def load_config(
    session: AsyncSession,
    doc_type: Optional[str] = None,
    template_id: Optional[str] = None,
) -> dict[str, Any]:
    """
    加载配置（通过模板方式）。

    根据参数解析模板，然后加载三个配置（fields、profile、aggregation）。

    Args:
        session: SQLAlchemy 异步会话。
        doc_type: 文档类型。
        template_id: 可选，强制指定的模板编号。

    Returns:
        dict: 合并后的配置字典，结构为：
            {
                "fields_schema": {...},  # 全局字段定义
                "profile": {...},        # 字段策略
                "agg_rules": {...},      # 聚合规则
                "template": {...},       # 使用的模板信息
                "trace": {...}           # 分流决策追踪
            }

    Raises:
        ConfigLoadError: 配置加载失败时抛出。
    """
    try:
        # 解析模板
        template, trace = await resolve_template(session, doc_type, template_id)

        logger.info(
            f"加载配置: template_id={template['template_id']}, "
            f"version={template['version']}, doc_type={doc_type}"
        )

        # 加载三个配置
        fields_schema = await get_config_by_id(session, template["fields_config_id"])
        profile = await get_config_by_id(session, template["profile_config_id"])
        agg_rules = await get_config_by_id(session, template["aggregation_config_id"])

        config_result = {
            "fields_schema": fields_schema,
            "profile": profile,
            "agg_rules": agg_rules or {},
            "template": {
                "template_id": template["template_id"],
                "version": template["version"],
                "weight": template["weight"],
                "pre_process": template.get("pre_process", ""),
            },
            "trace": trace,
        }

        logger.info(
            f"配置加载成功: fields_schema keys={list(fields_schema.keys())}, "
            f"profile fields={list(profile.get('fields', {}).keys())}"
        )

        return config_result

    except ConfigLoadError:
        raise
    except Exception as e:
        error_msg = f"配置加载失败: doc_type={doc_type}, template_id={template_id}, error={e}"
        logger.error(error_msg)
        raise ConfigLoadError(error_msg) from e
