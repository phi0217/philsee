"""
字段提取模块

根据字段配置调用 VLM 客户端获取原始响应，然后根据字段类型进行解析和转换。
支持 string、number、list、object 类型的自动解析，list/object 类型支持 JSON 解析失败重试。
"""

import json
import logging
from typing import Any, Optional

from vlm_client import VLMError, call_vlm

logger = logging.getLogger(__name__)


class FieldExtractionError(Exception):
    """字段提取异常"""

    pass


async def extract_field(
    image_base64: str,
    field_config: dict[str, Any],
    vlm_config: dict[str, Any],
    system_prompt: Optional[str] = None,
) -> tuple[Any, float, str]:
    """
    从图片中提取单个字段。

    根据字段配置调用 VLM 客户端获取响应，然后根据字段类型进行解析转换。

    Args:
        image_base64: 图片的 base64 字符串（已包含 data:image/jpeg;base64, 前缀）。
        field_config: 字段配置字典，包含：
            - field_name (str): 字段名称
            - type (str): 字段类型 ("string", "number", "list", "object")
            - prompt_hint (str): 辅助提示词
            可选：
            - item_schema (dict): 列表项结构（预留）
            - properties (dict): 对象属性结构（预留）
        vlm_config: VLM 客户端配置字典，包含：
            - endpoint (str): VLM 服务端点
            - model (str): 模型名称
            - api_key (str): API 密钥
            - max_tokens (int): 最大生成 token 数
            - temperature (float): 温度参数
            - max_retries (int): 最大重试次数
            - timeout (float): 超时秒数
        system_prompt: 可选，覆盖默认系统提示词。

    Returns:
        tuple[Any, float, str]: (解析后的值, 置信度, 原始响应字符串)。
            - value: 解析后的值，类型根据字段类型决定；解析失败返回 None。
            - confidence: 置信度（0~1）。
            - raw_response: VLM 返回的原始字符串。

    Raises:
        FieldExtractionError: VLM 调用失败时抛出。
    """
    # 提取字段配置
    field_name = field_config.get("field_name", "unknown")
    field_type = field_config.get("type", "string").lower()
    prompt_hint = field_config.get("prompt_hint", "")

    logger.info(f"开始提取字段: field_name={field_name}, type={field_type}")

    # 构建用户提示词
    user_prompt = f"请提取字段 '{field_name}'。{prompt_hint} 只输出字段值，不要额外解释。"

    # 提取 VLM 配置参数
    endpoint = vlm_config.get(
        "endpoint",
        "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    )
    model = vlm_config.get("model", "qwen3-vl-plus")
    api_key = vlm_config.get("api_key", "")
    max_tokens = vlm_config.get("max_tokens", 1024)
    temperature = vlm_config.get("temperature", 0.0)
    max_retries = vlm_config.get("max_retries", 2)
    timeout = vlm_config.get("timeout", 30.0)

    try:
        # 第一次调用 VLM
        raw_response, confidence = await call_vlm(
            image_base64=image_base64,
            user_prompt=user_prompt,
            system_prompt=system_prompt,
            endpoint=endpoint,
            model=model,
            api_key=api_key,
            max_tokens=max_tokens,
            temperature=temperature,
            max_retries=max_retries,
            timeout=timeout,
        )

        # 根据字段类型解析响应
        value = _parse_response(raw_response, field_type)

        # 如果是 list/object 类型且解析失败，尝试重试一次
        if value is None and field_type in ("list", "object"):
            logger.warning(
                f"字段 '{field_name}' JSON 解析失败，尝试重试（强调 JSON 格式）"
            )

            # 构建强调 JSON 格式的提示词
            retry_prompt = (
                f"请提取字段 '{field_name}'。{prompt_hint} "
                f"注意：必须只输出合法的 JSON 格式，不要包含任何其他文字或解释。"
            )

            try:
                raw_response, confidence = await call_vlm(
                    image_base64=image_base64,
                    user_prompt=retry_prompt,
                    system_prompt=system_prompt,
                    endpoint=endpoint,
                    model=model,
                    api_key=api_key,
                    max_tokens=max_tokens,
                    temperature=temperature,
                    max_retries=max_retries,
                    timeout=timeout,
                )

                value = _parse_response(raw_response, field_type)

                if value is not None:
                    logger.info(f"字段 '{field_name}' 重试解析成功")
                else:
                    logger.error(
                        f"字段 '{field_name}' 重试后仍无法解析为 {field_type}"
                    )

            except VLMError as e:
                logger.error(f"字段 '{field_name}' 重试调用失败: {e}")

        # 记录结果
        if value is not None:
            logger.info(
                f"字段 '{field_name}' 提取成功: type={field_type}, "
                f"confidence={confidence:.2f}"
            )
        else:
            logger.warning(
                f"字段 '{field_name}' 提取结果为 None: type={field_type}, "
                f"raw_response='{raw_response[:50]}...' "
                if len(raw_response) > 50
                else f"raw_response='{raw_response}'"
            )

        return value, confidence, raw_response

    except VLMError as e:
        error_msg = f"字段 '{field_name}' VLM 调用失败: {e}"
        logger.error(error_msg)
        raise FieldExtractionError(error_msg) from e


def _parse_response(raw_response: str, field_type: str) -> Any:
    """
    根据字段类型解析原始响应字符串。

    Args:
        raw_response: VLM 返回的原始字符串。
        field_type: 字段类型 ("string", "number", "list", "object")。

    Returns:
        Any: 解析后的值。解析失败返回 None。
    """
    if not raw_response:
        return None

    stripped = raw_response.strip()

    if field_type == "string":
        # 字符串类型直接返回（去除首尾空白）
        return stripped if stripped else None

    elif field_type == "number":
        # 数字类型尝试转换为 float
        try:
            # 尝试直接转换
            return float(stripped)
        except ValueError:
            # 尝试去除可能的千分位逗号
            try:
                cleaned = stripped.replace(",", "")
                return float(cleaned)
            except ValueError:
                logger.warning(f"无法将 '{stripped}' 转换为数字")
                return None

    elif field_type == "list":
        # 列表类型尝试 JSON 解析
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, list):
                return parsed
            else:
                # 如果解析结果不是列表，包装成列表
                logger.debug(f"JSON 解析结果不是列表，自动包装: {type(parsed)}")
                return [parsed]
        except json.JSONDecodeError:
            logger.warning(f"无法将响应解析为 JSON 列表: '{stripped[:50]}...'")
            return None

    elif field_type == "object":
        # 对象类型尝试 JSON 解析
        try:
            parsed = json.loads(stripped)
            if isinstance(parsed, dict):
                return parsed
            else:
                logger.warning(f"JSON 解析结果不是对象: {type(parsed)}")
                return None
        except json.JSONDecodeError:
            logger.warning(f"无法将响应解析为 JSON 对象: '{stripped[:50]}...'")
            return None

    else:
        logger.warning(f"未知的字段类型: {field_type}，按字符串处理")
        return stripped if stripped else None


if __name__ == "__main__":
    import argparse
    import asyncio
    import base64

    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    async def test():
        """测试入口：使用真实图片测试字段提取。"""
        parser = argparse.ArgumentParser(description="字段提取测试")
        parser.add_argument("--image", required=True, help="测试图片路径")
        parser.add_argument(
            "--field-name", default="test_field", help="字段名称"
        )
        parser.add_argument(
            "--type",
            choices=["string", "number", "list", "object"],
            default="string",
            help="字段类型",
        )
        parser.add_argument("--prompt-hint", default="", help="辅助提示词")
        parser.add_argument(
            "--endpoint",
            default="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            help="VLM 服务端点",
        )
        parser.add_argument("--model", default="qwen3-vl-plus", help="模型名称")
        parser.add_argument(
            "--api-key",
            default="sk-eb0a0c50ab534cf0bd991859558edbf2",
            help="API 密钥",
        )
        args = parser.parse_args()

        try:
            # 读取图片并编码为 base64
            with open(args.image, "rb") as f:
                image_bytes = f.read()
            b64_encoded = base64.b64encode(image_bytes).decode("utf-8")
            image_base64 = f"data:image/jpeg;base64,{b64_encoded}"

            # 构建字段配置
            field_config = {
                "field_name": args.field_name,
                "type": args.type,
                "prompt_hint": args.prompt_hint,
            }

            # 构建 VLM 配置
            vlm_config = {
                "endpoint": args.endpoint,
                "model": args.model,
                "api_key": args.api_key,
                "max_tokens": 1024,
                "temperature": 0.0,
                "max_retries": 2,
                "timeout": 30.0,
            }

            print(f"图片: {args.image}")
            print(f"字段名: {args.field_name}")
            print(f"字段类型: {args.type}")
            print(f"提示词: {args.prompt_hint or '(无)'}")
            print("-" * 50)

            # 调用提取函数
            value, confidence, raw_response = await extract_field(
                image_base64=image_base64,
                field_config=field_config,
                vlm_config=vlm_config,
            )

            print(f"原始响应: {raw_response}")
            print(f"解析结果: {value}")
            print(f"结果类型: {type(value).__name__}")
            print(f"置信度: {confidence:.2f}")

        except FileNotFoundError:
            print(f"错误: 找不到图片文件 {args.image}")
        except FieldExtractionError as e:
            print(f"字段提取错误: {e}")
        except Exception as e:
            print(f"未知错误: {e}")

    asyncio.run(test())
