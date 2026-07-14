"""
数据库写入模块（兼容层）

此文件保留用于向后兼容，实际代码已迁移至 services/db_service.py。
"""

from online.services.db_service import save_results, create_tables, DatabaseWriterError

__all__ = ["save_results", "create_tables", "DatabaseWriterError"]