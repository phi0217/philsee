"""
配置校验模块

提供 fields、profile、aggregation 配置的校验功能。
"""

import logging
from typing import Any, List

logger = logging.getLogger(__name__)


class ConfigValidationError(Exception):
    """配置校验异常"""

    pass


def validate_fields_config(config: dict[str, Any]) -> tuple[bool, str]:
    """
    校验 fields 配置。

    必须包含 "fields" 对象，其中每个字段必须有 "type" 属性。

    Args:
        config: fields 配置字典。

    Returns:
        tuple[bool, str]: (是否有效, 错误信息)。
    """
    if not isinstance(config, dict):
        return False, "配置必须是 JSON 对象"

    if "fields" not in config:
        return False, "配置必须包含 'fields' 字段"

    fields = config.get("fields")
    if not isinstance(fields, dict):
        return False, "'fields' 必须是对象"

    valid_types = {"string", "number", "date", "list", "object", "boolean"}

    for field_name, field_def in fields.items():
        if not isinstance(field_def, dict):
            return False, f"字段 '{field_name}' 定义必须是对象"

        if "type" not in field_def:
            return False, f"字段 '{field_name}' 缺少 'type' 属性"

        field_type = field_def.get("type")
        if field_type not in valid_types:
            return False, f"字段 '{field_name}' 的类型 '{field_type}' 无效，有效类型: {valid_types}"

    logger.info(f"fields 配置校验通过: 共 {len(fields)} 个字段")
    return True, ""


def validate_profile_config(config: dict[str, Any], expected_doc_type: str) -> tuple[bool, str]:
    """
    校验 profile 配置。

    必须包含 "doc_type"（与用户输入一致）和 "fields" 字段。

    Args:
        config: profile 配置字典。
        expected_doc_type: 期望的文档类型。

    Returns:
        tuple[bool, str]: (是否有效, 错误信息)。
    """
    if not isinstance(config, dict):
        return False, "配置必须是 JSON 对象"

    if "doc_type" not in config:
        return False, "配置必须包含 'doc_type' 字段"

    doc_type = config.get("doc_type")
    if doc_type != expected_doc_type:
        return False, f"doc_type '{doc_type}' 与期望值 '{expected_doc_type}' 不一致"

    if "fields" not in config:
        return False, "配置必须包含 'fields' 字段"

    fields = config.get("fields")
    if not isinstance(fields, dict):
        return False, "'fields' 必须是对象"

    logger.info(f"profile 配置校验通过: doc_type={doc_type}, 共 {len(fields)} 个字段")
    return True, ""


def validate_aggregation_config(
    config: dict[str, Any],
    profile_fields: List[str],
) -> tuple[bool, str]:
    """
    校验 aggregation 配置。

    所有字段名必须在 profile 中存在，策略必须合法。

    Args:
        config: aggregation 配置字典。
        profile_fields: profile 中的字段名列表。

    Returns:
        tuple[bool, str]: (是否有效, 错误信息)。
    """
    if not isinstance(config, dict):
        return False, "配置必须是 JSON 对象"

    valid_strategies = {"first", "last", "concat", "max", "min", "sum", "latest", "earliest"}

    # 检查是否有字段定义
    if "fields" in config:
        fields = config.get("fields")
        if not isinstance(fields, dict):
            return False, "'fields' 必须是对象"

        for field_name, field_rule in fields.items():
            # 检查字段是否在 profile 中存在
            if field_name not in profile_fields:
                return False, f"字段 '{field_name}' 不在 profile 的字段列表中"

            if isinstance(field_rule, dict):
                strategy = field_rule.get("strategy")
                if strategy and strategy not in valid_strategies:
                    return False, f"字段 '{field_name}' 的策略 '{strategy}' 无效，有效策略: {valid_strategies}"

    logger.info(f"aggregation 配置校验通过: 共 {len(config.get('fields', {}))} 个字段规则")
    return True, ""


def validate_json_structure(json_str: str) -> tuple[bool, dict | None, str]:
    """
    校验 JSON 字符串结构。

    Args:
        json_str: JSON 字符串。

    Returns:
        tuple[bool, dict | None, str]: (是否有效, 解析后的对象, 错误信息)。
    """
    import json

    try:
        parsed = json.loads(json_str)
        if not isinstance(parsed, dict):
            return False, None, "JSON 必须是对象"
        return True, parsed, ""
    except json.JSONDecodeError as e:
        return False, None, f"JSON 解析失败: {e}"


def extract_profile_field_names(profile: dict[str, Any]) -> List[str]:
    """
    从 profile 配置中提取字段名列表。

    Args:
        profile: profile 配置字典。

    Returns:
        List[str]: 字段名列表。
    """
    fields = profile.get("fields", {})
    return list(fields.keys())
