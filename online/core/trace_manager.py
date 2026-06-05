"""
请求追踪管理器

生成唯一的 trace_id（UUID），并提供内存字典存储每个请求的中间状态。
用于在单次请求的生命周期中，辅助传递和记录状态信息。
"""

import time
import uuid
from typing import Any

import logging

logger = logging.getLogger(__name__)


class TraceManager:
    """
    请求追踪管理器。

    管理请求的 trace_id 和中间状态，适用于单次请求生命周期内临时存储。
    由于是内存存储，服务重启后数据丢失。

    Attributes:
        _store: 存储 trace_id 到状态字典的映射。
    """

    def __init__(self) -> None:
        """初始化追踪管理器，创建空的状态存储。"""
        self._store: dict[str, dict[str, Any]] = {}
        logger.debug("TraceManager 初始化完成")

    def new_trace(self) -> str:
        """
        生成新的 trace_id 并初始化状态。

        使用 uuid.uuid4().hex 生成 32 位十六进制字符串作为唯一标识。
        自动初始化状态字典，包含状态和时间戳。

        Returns:
            str: 新生成的 trace_id。
        """
        trace_id = uuid.uuid4().hex
        created_at = time.time()

        self._store[trace_id] = {
            "status": "pending",
            "created_at": created_at,
        }

        logger.debug(f"创建新 trace: trace_id={trace_id}")
        return trace_id

    def update_state(self, trace_id: str, state: dict[str, Any]) -> None:
        """
        更新指定 trace_id 的状态。

        将传入的 state 字典合并到现有状态中。如果 trace_id 不存在，
        则创建新的状态条目。

        Args:
            trace_id: 请求唯一标识。
            state: 要更新的状态字典。
        """
        if trace_id not in self._store:
            # trace_id 不存在，创建新条目
            self._store[trace_id] = {
                "status": "unknown",
                "created_at": time.time(),
            }
            logger.debug(f"trace_id 不存在，创建新条目: trace_id={trace_id}")

        self._store[trace_id].update(state)
        logger.debug(f"更新状态: trace_id={trace_id}, state={state}")

    def get_state(self, trace_id: str) -> dict[str, Any]:
        """
        获取指定 trace_id 的状态。

        返回状态字典的副本，防止外部修改影响内部存储。

        Args:
            trace_id: 请求唯一标识。

        Returns:
            dict[str, Any]: 状态字典的副本。如果 trace_id 不存在，返回空字典。
        """
        state = self._store.get(trace_id, {})
        # 返回副本，防止外部修改
        return dict(state)

    def delete_trace(self, trace_id: str) -> bool:
        """
        删除指定 trace_id 的状态记录。

        Args:
            trace_id: 请求唯一标识。

        Returns:
            bool: 是否成功删除（trace_id 存在则返回 True）。
        """
        if trace_id in self._store:
            del self._store[trace_id]
            logger.debug(f"删除 trace: trace_id={trace_id}")
            return True
        return False

    def cleanup_old(self, max_age_seconds: float) -> int:
        """
        清理超过指定时间的旧记录。

        根据 created_at 时间戳判断记录是否过期。

        Args:
            max_age_seconds: 最大存活时间（秒）。

        Returns:
            int: 清理的记录数量。
        """
        current_time = time.time()
        expired_traces = [
            trace_id
            for trace_id, state in self._store.items()
            if state.get("created_at", 0) < current_time - max_age_seconds
        ]

        for trace_id in expired_traces:
            del self._store[trace_id]

        if expired_traces:
            logger.info(f"清理了 {len(expired_traces)} 条过期记录")

        return len(expired_traces)

    def get_all_traces(self) -> list[str]:
        """
        获取所有 trace_id 列表。

        Returns:
            list[str]: 所有 trace_id 的列表。
        """
        return list(self._store.keys())

    def count(self) -> int:
        """
        获取当前存储的 trace 数量。

        Returns:
            int: trace 数量。
        """
        return len(self._store)


# 全局单例实例
_global_manager: TraceManager | None = None


def get_trace_manager() -> TraceManager:
    """
    获取全局 TraceManager 单例实例。

    Returns:
        TraceManager: 全局单例实例。
    """
    global _global_manager
    if _global_manager is None:
        _global_manager = TraceManager()
    return _global_manager
