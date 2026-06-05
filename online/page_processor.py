"""
单页文档处理模块

根据当前页码和字段配置，串行调用 field_extractor 提取每个字段的值。
返回该页所有字段的提取结果列表，支持单个字段失败的容错处理。
"""

import asyncio
import logging
import time
from typing import Any, Optional

from online.field_extractor import extract_field, FieldExtractionError
from online.pipeline import execute_post_process_pipeline

logger = logging.getLogger(__name__)


async def process_page(
    image_base64: str,
    fields_config: list[dict[str, Any]],
    page_num: int,
    vlm_config: dict[str, Any],
    system_prompt: Optional[str] = None,
) -> list[dict[str, Any]]:
    """
    处理单页文档，提取所有配置的字段。

    串行调用 extract_field 提取每个字段，保持字段顺序。
    单个字段失败不会中断整页处理，而是记录错误并继续后续字段。

    Args:
        image_base64: 当前页图片的 base64 字符串（已包含 data:image/jpeg;base64, 前缀）。
        fields_config: 字段配置列表，每个元素是一个字典，包含：
            - field_name (str): 字段名称
            - type (str): 字段类型 ("string", "number", "list", "object")
            - prompt_hint (str): 辅助提示词
            可选：
            - pages (list[int] | str): 指定页码（调用方应已过滤）
        page_num: 当前页码（整数，从1开始），主要用于日志记录。
        vlm_config: VLM 客户端配置字典，直接传递给 extract_field。
        system_prompt: 可选，覆盖默认系统提示词（传递给 extract_field）。

    Returns:
        list[dict[str, Any]]: 字段提取结果列表，每个元素包含：
            - field_name (str): 字段名称
            - value (Any): 提取的值，失败时为 None
            - confidence (float): 置信度（0~1），失败时为 0.0
            - raw_response (str): 原始响应，失败时为异常信息
        顺序与 fields_config 中的字段顺序一致。
    """
    logger.info(f"开始处理第 {page_num} 页，共 {len(fields_config)} 个字段")

    page_results: list[dict[str, Any]] = []
    start_time = time.monotonic()

    for idx, field_config in enumerate(fields_config, start=1):
        field_name = field_config.get("field_name", "unknown")
        field_type = field_config.get("type", "string")

        logger.debug(
            f"第 {page_num} 页 - 处理字段 {idx}/{len(fields_config)}: "
            f"field_name={field_name}, type={field_type}"
        )

        field_start_time = time.monotonic()

        try:
            # 调用 extract_field 提取字段
            value, confidence, raw_response = await extract_field(
                image_base64=image_base64,
                field_config=field_config,
                vlm_config=vlm_config,
                system_prompt=system_prompt,
            )

            # 执行后处理管道（如果有配置）
            post_process = field_config.get("post_process", "")
            if post_process and value is not None:
                try:
                    value = execute_post_process_pipeline(value, post_process)
                    logger.debug(
                        f"第 {page_num} 页 - 字段 '{field_name}' 后处理完成: "
                        f"pipeline='{post_process}'"
                    )
                except ValueError as e:
                    logger.warning(
                        f"第 {page_num} 页 - 字段 '{field_name}' 后处理失败: {e}"
                    )

            field_elapsed = time.monotonic() - field_start_time

            logger.info(
                f"第 {page_num} 页 - 字段 '{field_name}' 提取成功: "
                f"confidence={confidence:.2f}, elapsed={field_elapsed:.2f}s"
            )

            page_results.append({
                "field_name": field_name,
                "value": value,
                "confidence": confidence,
                "raw_response": raw_response,
            })

        except FieldExtractionError as e:
            field_elapsed = time.monotonic() - field_start_time

            logger.error(
                f"第 {page_num} 页 - 字段 '{field_name}' 提取失败: {e}, "
                f"elapsed={field_elapsed:.2f}s"
            )

            page_results.append({
                "field_name": field_name,
                "value": None,
                "confidence": 0.0,
                "raw_response": str(e),
            })

        except Exception as e:
            field_elapsed = time.monotonic() - field_start_time

            logger.error(
                f"第 {page_num} 页 - 字段 '{field_name}' 发生未知异常: "
                f"{type(e).__name__}: {e}, elapsed={field_elapsed:.2f}s"
            )

            page_results.append({
                "field_name": field_name,
                "value": None,
                "confidence": 0.0,
                "raw_response": f"{type(e).__name__}: {str(e)}",
            })

    total_elapsed = time.monotonic() - start_time

    # 统计成功/失败数量
    success_count = sum(1 for r in page_results if r["confidence"] > 0)
    failure_count = len(page_results) - success_count

    logger.info(
        f"第 {page_num} 页处理完成: 成功={success_count}, 失败={failure_count}, "
        f"总耗时={total_elapsed:.2f}s"
    )

    return page_results
