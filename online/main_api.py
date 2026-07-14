"""
FastAPI 应用入口（兼容层）

此文件保留用于向后兼容，实际代码已迁移至 online/main.py。
"""

from online.main import app

__all__ = ["app"]