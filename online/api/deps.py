"""
API 依赖注入模块

提供 FastAPI 依赖注入函数。
"""

from online.core.trace_manager import get_trace_manager, TraceManager
from config.settings import settings


def get_vlm_config() -> dict:
    """
    获取 VLM 配置。

    Returns:
        dict: VLM 配置字典。
    """
    return settings.get_vlm_config()


def get_minio_config() -> dict:
    """
    获取 MinIO 配置。

    Returns:
        dict: MinIO 配置字典。
    """
    return settings.get_minio_config()


def get_image_config() -> dict:
    """
    获取图像处理配置。

    Returns:
        dict: 图像处理配置字典。
    """
    return {
        "target_short_edge": settings.image_target_short_edge,
    }


def get_trace_mgr() -> TraceManager:
    """
    获取追踪管理器实例。

    Returns:
        TraceManager: 追踪管理器实例。
    """
    return get_trace_manager()
