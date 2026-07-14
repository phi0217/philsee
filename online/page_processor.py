"""
单页文档处理模块（兼容层）

此文件保留用于向后兼容，实际代码已迁移至 processors/page_processor.py。
"""

from online.processors.page_processor import process_page

__all__ = ["process_page"]