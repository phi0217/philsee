"""
单页文档处理模块

根据当前页码和字段配置，串行调用 field_extractor 提取每个字段的值。
返回该页所有字段的提取结果列表，支持单个字段失败的容错处理。
"""

import asyncio
import logging
import time
from typing import Any, Optional

from field_extractor import extract_field, FieldExtractionError

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


if __name__ == "__main__":
    import argparse
    from unittest.mock import AsyncMock, patch

    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    async def test():
        """测试入口：验证串行调用顺序和异常处理。"""
        parser = argparse.ArgumentParser(description="单页文档处理测试")
        parser.add_argument(
            "--mock", action="store_true", help="使用模拟数据测试"
        )
        parser.add_argument(
            "--image", help="测试图片路径（真实测试时需要）"
        )
        parser.add_argument(
            "--api-key",
            default="sk-eb0a0c50ab534cf0bd991859558edbf2",
            help="API 密钥（真实测试时使用）",
        )
        args = parser.parse_args()

        # 构建测试字段配置
        fields = [
            {
                "field_name": "amount",
                "type": "number",
                "prompt_hint": "请提取金额数值",
            },
            {
                "field_name": "currency",
                "type": "string",
                "prompt_hint": "请提取币种代码",
            },
            {
                "field_name": "error_field",
                "type": "string",
                "prompt_hint": "这个字段会失败",
            },
            {
                "field_name": "unexpected_error",
                "type": "string",
                "prompt_hint": "这个字段会抛出未知异常",
            },
            {
                "field_name": "unknown",
                "type": "string",
                "prompt_hint": "返回 None",
            },
        ]

        if args.mock:
            # 使用模拟数据测试
            print("=" * 60)
            print("使用模拟数据测试（验证串行调用和异常处理）")
            print("=" * 60)

            # 定义模拟函数
            async def mock_extract_field(
                image_base64: str,
                field_config: dict[str, Any],
                vlm_config: dict[str, Any],
                system_prompt: Optional[str] = None,
            ) -> tuple[Any, float, str]:
                field_name = field_config.get("field_name", "unknown")

                if field_name == "amount":
                    return (1000.00, 0.9, "1000.00")
                elif field_name == "currency":
                    return ("USD", 0.95, "USD")
                elif field_name == "error_field":
                    raise FieldExtractionError(f"模拟字段 '{field_name}' 提取失败")
                elif field_name == "unexpected_error":
                    raise RuntimeError("模拟未知错误")
                else:
                    return (None, 0.0, "error")

            # 使用 patch 模拟 extract_field
            with patch("__main__.extract_field", new=AsyncMock(side_effect=mock_extract_field)):
                results = await process_page(
                    image_base64="data:image/jpeg;base64,mock_data",
                    fields_config=fields,
                    page_num=1,
                    vlm_config={},
                )

        else:
            # 真实测试
            if not args.image:
                print("错误: 真实测试需要 --image 参数")
                return

            import base64

            print("=" * 60)
            print(f"使用真实图片测试: {args.image}")
            print("=" * 60)

            try:
                # 读取图片并编码为 base64
                with open(args.image, "rb") as f:
                    image_bytes = f.read()
                b64_encoded = base64.b64encode(image_bytes).decode("utf-8")
                image_base64 = f"data:image/jpeg;base64,{b64_encoded}"

                # 构建 VLM 配置
                vlm_config = {
                    "endpoint": "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
                    "model": "qwen3-vl-plus",
                    "api_key": args.api_key,
                    "max_tokens": 1024,
                    "temperature": 0.0,
                    "max_retries": 2,
                    "timeout": 30.0,
                }

                results = await process_page(
                    image_base64=image_base64,
                    fields_config=fields,
                    page_num=1,
                    vlm_config=vlm_config,
                )

            except FileNotFoundError:
                print(f"错误: 找不到图片文件 {args.image}")
                return

        # 打印结果
        print("\n" + "=" * 60)
        print("提取结果:")
        print("=" * 60)

        for i, result in enumerate(results, start=1):
            print(f"\n字段 {i}: {result['field_name']}")
            print(f"  值: {result['value']}")
            print(f"  置信度: {result['confidence']:.2f}")
            print(f"  原始响应: {result['raw_response']}")

        # 验证结果顺序
        print("\n" + "=" * 60)
        print("验证:")
        print("=" * 60)
        field_names = [r["field_name"] for r in results]
        expected_names = [f["field_name"] for f in fields]
        print(f"字段顺序正确: {field_names == expected_names}")
        print(f"成功字段数: {sum(1 for r in results if r['confidence'] > 0)}")
        print(f"失败字段数: {sum(1 for r in results if r['confidence'] == 0)}")

    asyncio.run(test())
