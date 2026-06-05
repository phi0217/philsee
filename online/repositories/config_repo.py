"""
配置仓库模块

封装 config_versions 和 config_templates 表的数据库操作。
"""

import logging
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from online.models.config import ConfigVersion, ConfigTemplate

logger = logging.getLogger(__name__)


class ConfigRepository:
    """配置仓库类"""

    def __init__(self, session: AsyncSession):
        """
        初始化配置仓库。

        Args:
            session: SQLAlchemy 异步会话。
        """
        self.session = session

    async def get_config_by_id(self, config_id: int) -> Optional[dict[str, Any]]:
        """
        根据 ID 获取配置内容。

        Args:
            config_id: config_versions 表的主键 ID。

        Returns:
            配置内容字典，不存在则返回 None。
        """
        query = select(ConfigVersion).where(
            ConfigVersion.id == config_id,
            ConfigVersion.is_deleted == False,  # noqa: E712
        )
        result = await self.session.execute(query)
        config = result.scalar_one_or_none()

        if config is None:
            return None

        return config.content

    async def get_config_version(self, config_id: int) -> Optional[ConfigVersion]:
        """
        根据 ID 获取配置版本记录。

        Args:
            config_id: config_versions 表的主键 ID。

        Returns:
            ConfigVersion 模型实例，不存在则返回 None。
        """
        query = select(ConfigVersion).where(
            ConfigVersion.id == config_id,
            ConfigVersion.is_deleted == False,  # noqa: E712
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def get_active_templates(
        self,
        template_id: Optional[str] = None,
        doc_type: Optional[str] = None,
    ) -> list[ConfigTemplate]:
        """
        获取激活的模板列表。

        Args:
            template_id: 可选，模板编号筛选。
            doc_type: 可选，文档类型筛选。

        Returns:
            激活的模板列表。
        """
        query = select(ConfigTemplate).where(ConfigTemplate.is_active == True)  # noqa: E712

        if template_id:
            query = query.where(ConfigTemplate.template_id == template_id)
        if doc_type:
            query = query.where(ConfigTemplate.doc_type == doc_type)

        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_template_by_id(self, template_id: int) -> Optional[ConfigTemplate]:
        """
        根据 ID 获取模板。

        Args:
            template_id: config_templates 表的主键 ID。

        Returns:
            ConfigTemplate 模型实例，不存在则返回 None。
        """
        query = select(ConfigTemplate).where(ConfigTemplate.id == template_id)
        result = await self.session.execute(query)
        return result.scalar_one_or_none()

    async def insert_config_version(
        self,
        version_tag: str,
        doc_type: str,
        config_type: str,
        content: dict[str, Any],
        created_by: Optional[str] = None,
    ) -> ConfigVersion:
        """
        插入新的配置版本记录。

        Args:
            version_tag: 版本标识。
            doc_type: 文档类型。
            config_type: 配置类型。
            content: 配置内容。
            created_by: 创建人。

        Returns:
            新创建的 ConfigVersion 实例。
        """
        config = ConfigVersion(
            version_tag=version_tag,
            doc_type=doc_type,
            config_type=config_type,
            content=content,
            created_by=created_by,
        )
        self.session.add(config)
        await self.session.flush()
        return config

    async def insert_template(
        self,
        template_id: str,
        version: str,
        doc_type: str,
        fields_config_id: int,
        profile_config_id: int,
        aggregation_config_id: int,
        description: Optional[str] = None,
        pre_process: Optional[str] = None,
        is_active: bool = True,
        weight: int = 100,
        created_by: Optional[str] = None,
    ) -> ConfigTemplate:
        """
        插入新的模板记录。

        Args:
            template_id: 模板编号。
            version: 模板版本。
            doc_type: 文档类型。
            fields_config_id: 字段配置 ID。
            profile_config_id: 字段策略配置 ID。
            aggregation_config_id: 聚合规则配置 ID。
            description: 模板说明。
            pre_process: 前处理管道。
            is_active: 是否启用。
            weight: 分流权重。
            created_by: 创建人。

        Returns:
            新创建的 ConfigTemplate 实例。
        """
        template = ConfigTemplate(
            template_id=template_id,
            version=version,
            doc_type=doc_type,
            description=description,
            fields_config_id=fields_config_id,
            profile_config_id=profile_config_id,
            aggregation_config_id=aggregation_config_id,
            pre_process=pre_process,
            is_active=is_active,
            weight=weight,
            created_by=created_by,
        )
        self.session.add(template)
        await self.session.flush()
        return template

    async def check_config_exists(
        self,
        doc_type: str,
        config_type: str,
        version_tag: str,
    ) -> bool:
        """
        检查配置版本是否存在。

        Args:
            doc_type: 文档类型。
            config_type: 配置类型。
            version_tag: 版本标识。

        Returns:
            存在返回 True，否则返回 False。
        """
        query = select(ConfigVersion).where(
            ConfigVersion.doc_type == doc_type,
            ConfigVersion.config_type == config_type,
            ConfigVersion.version_tag == version_tag,
            ConfigVersion.is_deleted == False,  # noqa: E712
        )
        result = await self.session.execute(query)
        return result.scalar_one_or_none() is not None
