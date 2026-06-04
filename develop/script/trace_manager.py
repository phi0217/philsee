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


# 全局单例实例（可选使用）
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


if __name__ == "__main__":
    import logging

    # 配置日志
    logging.basicConfig(
        level=logging.DEBUG,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    print("=" * 60)
    print("TraceManager 功能测试")
    print("=" * 60)

    # 创建管理器实例
    tm = TraceManager()

    # 测试 1: 生成新 trace
    print("\n[测试 1] 生成新 trace_id")
    tid = tm.new_trace()
    print(f"  新 trace_id: {tid}")
    print(f"  长度: {len(tid)} 字符")

    # 测试 2: 获取初始状态
    print("\n[测试 2] 获取初始状态")
    state = tm.get_state(tid)
    print(f"  状态: {state}")

    # 测试 3: 更新状态
    print("\n[测试 3] 更新状态")
    tm.update_state(tid, {"page": 1, "status": "processing"})
    state = tm.get_state(tid)
    print(f"  更新后状态: {state}")

    # 测试 4: 再次更新（合并）
    print("\n[测试 4] 再次更新状态（合并）")
    tm.update_state(tid, {"page": 2, "progress": "50%"})
    state = tm.get_state(tid)
    print(f"  合并后状态: {state}")

    # 测试 5: 获取不存在的 trace
    print("\n[测试 5] 获取不存在的 trace_id")
    state = tm.get_state("non-existing-trace-id")
    print(f"  状态: {state}")
    print(f"  是否为空字典: {state == {}}")

    # 测试 6: 更新不存在的 trace（自动创建）
    print("\n[测试 6] 更新不存在的 trace_id（自动创建）")
    tm.update_state("auto-created", {"custom_field": "value"})
    state = tm.get_state("auto-created")
    print(f"  自动创建后状态: {state}")

    # 测试 7: 删除 trace
    print("\n[测试 7] 删除 trace")
    deleted = tm.delete_trace("auto-created")
    print(f"  删除结果: {deleted}")
    state = tm.get_state("auto-created")
    print(f"  删除后状态: {state}")

    # 测试 8: 统计和列表
    print("\n[测试 8] 统计和列表")
    tid2 = tm.new_trace()
    tid3 = tm.new_trace()
    print(f"  当前 trace 数量: {tm.count()}")
    print(f"  所有 trace_id: {tm.get_all_traces()}")

    # 测试 9: 清理过期记录
    print("\n[测试 9] 清理过期记录")
    # 创建一个旧记录（模拟）
    old_tid = tm.new_trace()
    # 手动设置创建时间为 2 小时前
    tm._store[old_tid]["created_at"] = time.time() - 7200
    print(f"  清理前 trace 数量: {tm.count()}")
    cleaned = tm.cleanup_old(max_age_seconds=3600)  # 清理 1 小时前的记录
    print(f"  清理的记录数: {cleaned}")
    print(f"  清理后 trace 数量: {tm.count()}")

    # 测试 10: 全局单例
    print("\n[测试 10] 全局单例")
    gm1 = get_trace_manager()
    gm2 = get_trace_manager()
    print(f"  是否为同一实例: {gm1 is gm2}")

    # 验证结果
    print("\n" + "=" * 60)
    print("验证结果")
    print("=" * 60)

    tests_passed = 0
    tests_total = 5

    # 验证 trace_id 格式
    if len(tid) == 32 and all(c in "0123456789abcdef" for c in tid):
        print("  ✓ trace_id 格式正确（32位十六进制）")
        tests_passed += 1
    else:
        print("  ✗ trace_id 格式错误")

    # 验证状态合并
    final_state = tm.get_state(tid)
    if final_state.get("page") == 2 and final_state.get("status") == "processing":
        print("  ✓ 状态合并正确")
        tests_passed += 1
    else:
        print("  ✗ 状态合并错误")

    # 验证不存在 trace 返回空字典
    if tm.get_state("non-existing") == {}:
        print("  ✓ 不存在的 trace 返回空字典")
        tests_passed += 1
    else:
        print("  ✗ 不存在的 trace 返回值错误")

    # 验证删除功能
    if tm.delete_trace(tid) and tid not in tm.get_all_traces():
        print("  ✓ 删除功能正常")
        tests_passed += 1
    else:
        print("  ✗ 删除功能错误")

    # 验证清理功能
    if cleaned >= 1:
        print("  ✓ 清理功能正常")
        tests_passed += 1
    else:
        print("  ✗ 清理功能错误")

    print(f"\n测试通过: {tests_passed}/{tests_total}")
