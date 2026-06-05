"""
配置加载模块（兼容层）

此文件保留用于向后兼容，实际代码已迁移至：
- online/models/config.py（模型定义）
- online/services/config_service.py（服务函数）
"""

# 从新位置重新导出模型
from online.models.config import ConfigVersion, ConfigTemplate, Base

# 从新位置重新导出服务函数
from online.services.config_service import (
    ConfigLoadError,
    get_config_by_id,
    get_active_templates,
    select_template,
    resolve_template,
    load_config,
    DEFAULT_TEMPLATE_MAP,
)

__all__ = [
    # 模型
    "Base",
    "ConfigVersion",
    "ConfigTemplate",
    # 异常
    "ConfigLoadError",
    # 服务函数
    "get_config_by_id",
    "get_active_templates",
    "select_template",
    "resolve_template",
    "load_config",
    "DEFAULT_TEMPLATE_MAP",
]
