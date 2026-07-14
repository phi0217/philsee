"""
字段提取模块（兼容层）

此文件保留用于向后兼容，实际代码已迁移至 processors/field_extractor.py。
"""

from online.processors.field_extractor import extract_field, FieldExtractionError

__all__ = ["extract_field", "FieldExtractionError"]