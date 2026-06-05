"""
VLM 客户端模块（兼容层）

此文件保留用于向后兼容，实际代码已迁移至 online/core/vlm_client.py。
"""

# 从新位置重新导出
from online.core.vlm_client import (
    call_vlm,
    VLMError,
    _extract_confidence,
)

__all__ = ["call_vlm", "VLMError", "_extract_confidence"]
