"""
跨页字段聚合模块（兼容层）

此文件保留用于向后兼容，实际代码已迁移至 services/aggregator_service.py。
"""

from online.services.aggregator_service import aggregate_results

__all__ = ["aggregate_results"]