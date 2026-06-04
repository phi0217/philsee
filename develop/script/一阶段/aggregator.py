"""
跨页字段聚合模块

接收所有页的字段提取结果，根据配置的聚合规则对每个字段进行合并处理，
生成最终的文档级字段值。支持四种聚合策略：
- first_non_null: 按页码顺序取第一个非空值
- last_non_null: 按页码顺序取最后一个非空值
- max_confidence: 取置信度最高的值
- merge_lists: 按页码顺序合并所有页的列表
"""

import logging
from typing import Any

logger = logging.getLogger(__name__)


def aggregate_results(
    all_page_results: list[list[dict[str, Any]]],
    agg_rules: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    """
    聚合所有页面的字段提取结果。

    根据聚合规则对每个字段进行合并处理，生成最终的文档级字段值，
    同时记录聚合决策信息。

    Args:
        all_page_results: 所有页面的字段提取结果列表，每个元素是一页的结果列表。
            每个结果字典应包含：
            - field_name (str): 字段名称
            - value (Any): 提取的值
            - confidence (float): 置信度
            - page (int): 页码（从1开始）
        agg_rules: 聚合规则字典，格式：
            {
                "field_name": {"strategy": "first_non_null"},
                "default": {"strategy": "first_non_null"}
            }
            支持的策略：first_non_null, last_non_null, max_confidence, merge_lists

    Returns:
        tuple[dict[str, Any], dict[str, Any]]:
            - aggregated_fields: {field_name: final_value}
            - agg_decisions: {field_name: {
                "selected_page": int | None,
                "reason": str,
                "candidates": list[dict]
              }}
    """
    logger.info(f"开始聚合，共 {len(all_page_results)} 页结果")

    # 步骤1：按字段名重新组织数据
    field_candidates: dict[str, list[dict[str, Any]]] = {}

    for page_idx, page_results in enumerate(all_page_results):
        for result in page_results:
            field_name = result.get("field_name")
            if field_name is None:
                logger.warning(f"结果缺少 field_name，跳过: {result}")
                continue

            # 获取页码，如果没有则使用索引+1
            page_num = result.get("page")
            if page_num is None:
                page_num = page_idx + 1
                logger.warning(
                    f"字段 '{field_name}' 结果缺少 page 键，使用推断页码: {page_num}"
                )

            candidate = {
                "page": page_num,
                "value": result.get("value"),
                "confidence": result.get("confidence", 0.0),
            }

            if field_name not in field_candidates:
                field_candidates[field_name] = []
            field_candidates[field_name].append(candidate)

    logger.info(f"共发现 {len(field_candidates)} 个字段需要聚合")

    # 步骤2：获取默认策略
    default_rule = agg_rules.get("default", {"strategy": "first_non_null"})
    default_strategy = default_rule.get("strategy", "first_non_null")

    # 步骤3：对每个字段应用聚合策略
    aggregated_fields: dict[str, Any] = {}
    agg_decisions: dict[str, Any] = {}

    for field_name, candidates in field_candidates.items():
        # 按页码排序
        candidates.sort(key=lambda x: x["page"])

        # 获取该字段的聚合策略
        field_rule = agg_rules.get(field_name, default_rule)
        strategy = field_rule.get("strategy", default_strategy)

        logger.debug(
            f"字段 '{field_name}' 使用策略 '{strategy}'，候选数: {len(candidates)}"
        )

        # 根据策略计算最终值
        if strategy == "first_non_null":
            final_value, selected_page, reason = _aggregate_first_non_null(candidates)
        elif strategy == "last_non_null":
            final_value, selected_page, reason = _aggregate_last_non_null(candidates)
        elif strategy == "max_confidence":
            final_value, selected_page, reason = _aggregate_max_confidence(candidates)
        elif strategy == "merge_lists":
            final_value, selected_page, reason = _aggregate_merge_lists(
                candidates, field_name
            )
        else:
            logger.warning(
                f"字段 '{field_name}' 使用未知策略 '{strategy}'，回退到 first_non_null"
            )
            final_value, selected_page, reason = _aggregate_first_non_null(candidates)

        aggregated_fields[field_name] = final_value
        agg_decisions[field_name] = {
            "selected_page": selected_page,
            "reason": reason,
            "candidates": candidates,
        }

        logger.info(
            f"字段 '{field_name}' 聚合完成: strategy={strategy}, "
            f"selected_page={selected_page}, value={final_value}"
        )

    return aggregated_fields, agg_decisions


def _aggregate_first_non_null(
    candidates: list[dict[str, Any]],
) -> tuple[Any, int | None, str]:
    """
    first_non_null 策略：按页码顺序取第一个非空值。

    Args:
        candidates: 候选值列表，已按页码排序。

    Returns:
        tuple[Any, int | None, str]: (最终值, 选中页码, 原因)
    """
    for candidate in candidates:
        if candidate["value"] is not None:
            return (
                candidate["value"],
                candidate["page"],
                f"first_non_null: page {candidate['page']}",
            )

    # 全部为空
    return None, None, "first_non_null_all_none"


def _aggregate_last_non_null(
    candidates: list[dict[str, Any]],
) -> tuple[Any, int | None, str]:
    """
    last_non_null 策略：按页码顺序取最后一个非空值。

    Args:
        candidates: 候选值列表，已按页码排序。

    Returns:
        tuple[Any, int | None, str]: (最终值, 选中页码, 原因)
    """
    last_non_null_candidate = None

    for candidate in candidates:
        if candidate["value"] is not None:
            last_non_null_candidate = candidate

    if last_non_null_candidate is not None:
        return (
            last_non_null_candidate["value"],
            last_non_null_candidate["page"],
            f"last_non_null: page {last_non_null_candidate['page']}",
        )

    # 全部为空
    return None, None, "last_non_null_all_none"


def _aggregate_max_confidence(
    candidates: list[dict[str, Any]],
) -> tuple[Any, int | None, str]:
    """
    max_confidence 策略：取置信度最高的值。

    置信度相同时取页码较小的。

    Args:
        candidates: 候选值列表，已按页码排序。

    Returns:
        tuple[Any, int | None, str]: (最终值, 选中页码, 原因)
    """
    best_candidate = None
    best_confidence = -1.0

    for candidate in candidates:
        confidence = candidate["confidence"]
        # 置信度更高，或置信度相同但页码更小（由于已排序，同置信度取第一个）
        if confidence > best_confidence:
            best_candidate = candidate
            best_confidence = confidence

    if best_candidate is not None and best_candidate["value"] is not None:
        return (
            best_candidate["value"],
            best_candidate["page"],
            f"max_confidence: page {best_candidate['page']} (confidence={best_confidence:.2f})",
        )

    # 最佳候选值为空或所有置信度都为0且值为空
    if best_candidate is not None:
        return (
            None,
            best_candidate["page"],
            f"max_confidence: best value is None (confidence={best_confidence:.2f})",
        )

    return None, None, "max_confidence_all_none"


def _aggregate_merge_lists(
    candidates: list[dict[str, Any]],
    field_name: str,
) -> tuple[list[Any], None, str]:
    """
    merge_lists 策略：按页码顺序合并所有页的列表。

    Args:
        candidates: 候选值列表，已按页码排序。
        field_name: 字段名称（用于日志）。

    Returns:
        tuple[list[Any], None, str]: (合并后的列表, None, 原因)
    """
    merged_list: list[Any] = []
    merged_count = 0
    skipped_count = 0

    for candidate in candidates:
        value = candidate["value"]
        page = candidate["page"]

        if value is None:
            logger.debug(f"字段 '{field_name}' 第 {page} 页值为 None，跳过")
            continue

        if isinstance(value, list):
            merged_list.extend(value)
            merged_count += 1
            logger.debug(
                f"字段 '{field_name}' 第 {page} 页合并了 {len(value)} 个元素"
            )
        else:
            logger.warning(
                f"字段 '{field_name}' 第 {page} 页值不是列表类型 ({type(value).__name__})，跳过"
            )
            skipped_count += 1

    if skipped_count > 0:
        logger.warning(
            f"字段 '{field_name}' merge_lists 跳过了 {skipped_count} 个非列表值"
        )

    logger.info(
        f"字段 '{field_name}' merge_lists 完成: 合并了 {merged_count} 页，"
        f"共 {len(merged_list)} 个元素"
    )

    return merged_list, None, f"merge_lists: merged {merged_count} pages"


if __name__ == "__main__":
    import logging

    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # 模拟两页结果
    page1 = [
        {"field_name": "amount", "value": 100, "confidence": 0.9, "page": 1},
        {
            "field_name": "commodities",
            "value": [{"id": 1, "name": "item1"}],
            "confidence": 0.8,
            "page": 1,
        },
        {"field_name": "currency", "value": "USD", "confidence": 0.95, "page": 1},
        {"field_name": "date", "value": None, "confidence": 0.0, "page": 1},
    ]
    page2 = [
        {"field_name": "amount", "value": 200, "confidence": 0.95, "page": 2},
        {
            "field_name": "commodities",
            "value": [{"id": 2, "name": "item2"}],
            "confidence": 0.9,
            "page": 2,
        },
        {"field_name": "currency", "value": "CNY", "confidence": 0.8, "page": 2},
        {"field_name": "date", "value": "2024-01-01", "confidence": 0.9, "page": 2},
    ]
    page3 = [
        {"field_name": "amount", "value": 150, "confidence": 0.85, "page": 3},
        {"field_name": "commodities", "value": "not_a_list", "confidence": 0.7, "page": 3},
        {"field_name": "currency", "value": None, "confidence": 0.0, "page": 3},
    ]

    # 聚合规则
    rules = {
        "amount": {"strategy": "max_confidence"},
        "commodities": {"strategy": "merge_lists"},
        "currency": {"strategy": "first_non_null"},
        "date": {"strategy": "last_non_null"},
        "default": {"strategy": "first_non_null"},
    }

    print("=" * 60)
    print("测试聚合功能")
    print("=" * 60)

    fields, decisions = aggregate_results([page1, page2, page3], rules)

    print("\n" + "=" * 60)
    print("聚合结果:")
    print("=" * 60)
    for field_name, value in fields.items():
        print(f"  {field_name}: {value}")

    print("\n" + "=" * 60)
    print("聚合决策:")
    print("=" * 60)
    for field_name, decision in decisions.items():
        print(f"\n  {field_name}:")
        print(f"    selected_page: {decision['selected_page']}")
        print(f"    reason: {decision['reason']}")
        print(f"    candidates: {decision['candidates']}")

    # 验证结果
    print("\n" + "=" * 60)
    print("验证:")
    print("=" * 60)

    tests = [
        ("amount", 200, "max_confidence 应选第2页的200"),
        ("commodities", [{"id": 1, "name": "item1"}, {"id": 2, "name": "item2"}], "merge_lists 应合并两个列表"),
        ("currency", "USD", "first_non_null 应选第1页的USD"),
        ("date", "2024-01-01", "last_non_null 应选第2页的日期"),
    ]

    all_passed = True
    for field_name, expected, description in tests:
        actual = fields.get(field_name)
        passed = actual == expected
        status = "✓" if passed else "✗"
        print(f"  {status} {field_name}: {description}")
        if not passed:
            print(f"      期望: {expected}")
            print(f"      实际: {actual}")
            all_passed = False

    print(f"\n所有测试: {'通过' if all_passed else '失败'}")
