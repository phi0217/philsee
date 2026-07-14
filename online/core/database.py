"""
数据库连接管理

提供异步数据库引擎和会话管理。
"""

import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config.settings import settings

logger = logging.getLogger(__name__)

# 创建异步数据库引擎
engine = create_async_engine(
    settings.get_db_url(),
    echo=settings.debug,
    pool_pre_ping=True,
)

# 创建异步会话工厂
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def init_database() -> None:
    """
    初始化数据库连接。

    创建表（如果不存在）。
    """
    from sqlalchemy import text

    async with engine.begin() as conn:
        # 简单的连接测试
        await conn.execute(text("SELECT 1"))

    logger.info("数据库连接初始化完成")


async def close_database() -> None:
    """
    关闭数据库连接池。
    """
    await engine.dispose()
    logger.info("数据库连接已关闭")
