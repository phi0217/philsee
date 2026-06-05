"""
请求追踪管理器（兼容层）

此文件保留用于向后兼容，实际代码已迁移至 online/core/trace_manager.py。
"""

# 从新位置重新导出
from online.core.trace_manager import (
    TraceManager,
    get_trace_manager,
)

__all__ = ["TraceManager", "get_trace_manager"]
