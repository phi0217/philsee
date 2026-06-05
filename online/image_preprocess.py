"""
图像预处理模块（兼容层）

此文件保留用于向后兼容，实际代码已迁移至 online/processors/image_preprocess.py。
"""

# 从新位置重新导出
from online.processors.image_preprocess import (
    preprocess_image,
    encode_to_base64,
)

__all__ = ["preprocess_image", "encode_to_base64"]
