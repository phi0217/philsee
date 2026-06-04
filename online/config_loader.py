"""
配置加载模块

从 MySQL 数据库的 config_versions 表中加载指定单据类型的配置，
包括全局字段定义、字段提取策略和跨页聚合规则。
"""

import json
import logging
from typing import Any, Optional

from sqlalchemy import JSON, select, text
from sqlalchemy.dialects.mysql import ENUM
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# 配置日志
logger = logging.getLogger(__name__)


class ConfigLoadError(Exception):
    """配置加载异常"""

    pass


class Base(DeclarativeBase):
    """SQLAlchemy 声明式基类"""

    pass


class ConfigVersion(Base):
    """config_versions 表模型"""

    __tablename__ = "config_versions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    version_tag: Mapped[str] = mapped_column(nullable=False)
    doc_type: Mapped[str] = mapped_column(nullable=False)
    config_type: Mapped[str] = mapped_column(
        ENUM("fields", "profile", "aggregation"), nullable=False
    )
    content: Mapped[dict] = mapped_column(JSON, nullable=False)
    created_at: Mapped[Optional[str]] = mapped_column(default=None)
    created_by: Mapped[Optional[str]] = mapped_column(default=None)
    is_active: Mapped[bool] = mapped_column(default=False)
    is_deleted: Mapped[bool] = mapped_column(default=False)


async def load_config(
    db_url: str, doc_type: str, version: Optional[str] = None
) -> dict[str, Any]:
    """
    从数据库加载指定单据类型的配置。

    加载全局字段定义（fields）、字段提取策略（profile）和跨页聚合规则（aggregation）。
    支持加载当前激活版本（is_active=True）或指定版本标签。

    Args:
        db_url: 数据库连接 URL（如 mysql+aiomysql://user:pass@localhost:3306/db）
        doc_type: 单据类型（如 "letter_of_credit"）
        version: 可选，指定配置版本标签（如 "v1.0.0"），若为 None 则加载激活版本

    Returns:
        dict: 合并后的配置字典，结构为：
            {
                "fields_schema": {...},  # 全局字段定义
                "profile": {...},        # 该 doc_type 的字段策略
                "agg_rules": {...}       # 聚合规则（回退到全局 '*'）
            }

    Raises:
        ConfigLoadError: 配置加载失败时抛出
        ValueError: 缺少必要配置（fields 或 profile）时抛出
    """
    engine = None

    try:
        # 创建异步引擎
        engine = create_async_engine(db_url, echo=False)
        async_session = async_sessionmaker(engine, class_=AsyncSession)

        async with async_session() as session:
            # 构建查询条件
            version_desc = version if version else "激活版本"
            logger.info(f"加载配置: doc_type={doc_type}, version={version_desc}")

            # 查询条件：doc_type IN (:doc_type, '*'), config_type IN ('fields','profile','aggregation')
            # 若指定 version，则 version_tag = :version；否则 is_active=True
            if version:
                query = select(ConfigVersion).where(
                    ConfigVersion.doc_type.in_([doc_type, "*"]),
                    ConfigVersion.config_type.in_(["fields", "profile", "aggregation"]),
                    ConfigVersion.version_tag == version,
                    ConfigVersion.is_deleted == False,  # noqa: E712
                )
            else:
                query = select(ConfigVersion).where(
                    ConfigVersion.doc_type.in_([doc_type, "*"]),
                    ConfigVersion.config_type.in_(["fields", "profile", "aggregation"]),
                    ConfigVersion.is_active == True,  # noqa: E712
                    ConfigVersion.is_deleted == False,  # noqa: E712
                )

            result = await session.execute(query)
            configs = result.scalars().all()

            if not configs:
                raise ConfigLoadError(
                    f"未找到配置: doc_type={doc_type}, version={version_desc}"
                )

            # 解析配置
            fields_schema = None
            profile = None
            agg_rules = None
            agg_rules_global = None

            for config in configs:
                content = config.content
                cfg_type = config.config_type
                cfg_doc_type = config.doc_type

                if cfg_type == "fields" and cfg_doc_type == "*":
                    # fields 的 doc_type 应为 '*'（全局）
                    fields_schema = content
                    logger.debug(f"加载 fields_schema: version_tag={config.version_tag}")

                elif cfg_type == "profile" and cfg_doc_type == doc_type:
                    # profile 的 doc_type 应为传入的 doc_type
                    profile = content
                    logger.debug(f"加载 profile: version_tag={config.version_tag}")

                elif cfg_type == "aggregation":
                    # aggregation 优先取 doc_type 匹配的，若不存在则取 doc_type='*' 的默认规则
                    if cfg_doc_type == doc_type:
                        agg_rules = content
                        logger.debug(
                            f"加载 agg_rules (特定): version_tag={config.version_tag}"
                        )
                    elif cfg_doc_type == "*":
                        agg_rules_global = content
                        logger.debug(
                            f"加载 agg_rules (全局): version_tag={config.version_tag}"
                        )

            # 验证必要配置
            if fields_schema is None:
                raise ValueError(f"缺少全局字段定义 (fields)，doc_type={doc_type}")
            if profile is None:
                raise ValueError(f"缺少字段策略 (profile)，doc_type={doc_type}")

            # 聚合规则允许回退到全局默认
            if agg_rules is None:
                agg_rules = agg_rules_global

            config_result = {
                "fields_schema": fields_schema,
                "profile": profile,
                "agg_rules": agg_rules or {},
            }

            logger.info(
                f"配置加载成功: fields_schema keys={list(fields_schema.keys())}, "
                f"profile fields={list(profile.get('fields', {}).keys())}, "
                f"agg_rules={'已加载' if agg_rules else '无'}"
            )

            return config_result

    except ValueError:
        raise
    except ConfigLoadError:
        raise
    except Exception as e:
        error_msg = f"配置加载失败: {e}"
        logger.error(error_msg)
        raise ConfigLoadError(error_msg) from e

    finally:
        # 确保引擎正确关闭
        if engine:
            await engine.dispose()
