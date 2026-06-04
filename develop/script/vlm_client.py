"""
VLM 客户端模块

异步调用外部 VLM（视觉大模型）接口，兼容 OpenAI 多模态聊天补全格式。
支持自动重试（指数退避）、超时控制、置信度提取等功能。
"""

import asyncio
import json
import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)


class VLMError(Exception):
    """VLM 调用异常"""

    pass


async def call_vlm(
    image_base64: str,
    user_prompt: str,
    system_prompt: Optional[str] = None,
    endpoint: str = "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
    model: str = "qwen3-vl-plus",
    api_key: str = "",
    max_tokens: int = 1024,
    temperature: float = 0.0,
    max_retries: int = 2,
    timeout: float = 30.0,
) -> tuple[str, float]:
    """
    异步调用 VLM 接口，提取图片中的字段信息。

    Args:
        image_base64: 图片的 base64 字符串（已包含 data:image/jpeg;base64, 前缀）。
        user_prompt: 用户提示词，描述需要提取的字段及要求。
        system_prompt: 系统提示词，默认为单据解析专家提示。
        endpoint: VLM 服务端点 URL。
        model: 模型名称。
        api_key: API 密钥（可选，空字符串表示无需认证）。
        max_tokens: 最大生成 token 数。
        temperature: 温度参数。
        max_retries: 最大重试次数。
        timeout: 请求超时秒数。

    Returns:
        tuple[str, float]: (响应文本, 置信度)。
            - response_text: VLM 返回的原始文本（已去除首尾空白）。
            - confidence: 置信度（0~1），优先从响应解析，否则根据文本是否为空计算。

    Raises:
        VLMError: 调用失败时抛出（重试次数用尽后）。
    """
    # 默认系统提示词
    if system_prompt is None:
        system_prompt = "你是一个单据解析专家。每次只提取一个字段，只输出字段值，不要输出任何额外文字。如果字段不存在，输出空字符串。"

    # 构建请求体
    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": system_prompt},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": image_base64}},
                    {"type": "text", "text": user_prompt},
                ],
            },
        ],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }

    # 构建请求头
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"

    # 重试配置
    retry_count = 0
    last_exception: Optional[Exception] = None

    async with httpx.AsyncClient(timeout=timeout) as client:
        while retry_count <= max_retries:
            try:
                logger.debug(
                    f"调用 VLM: endpoint={endpoint}, model={model}, retry={retry_count}/{max_retries}"
                )

                import time

                start_time = time.time()

                response = await client.post(
                    endpoint,
                    json=request_body,
                    headers=headers,
                )

                # 检查 HTTP 状态
                response.raise_for_status()

                elapsed = time.time() - start_time
                logger.debug(f"VLM 响应成功: elapsed={elapsed:.2f}s")

                # 解析响应
                data = response.json()
                response_text = data["choices"][0]["message"]["content"]
                response_text = response_text.strip() if response_text else ""

                # 提取置信度
                confidence = _extract_confidence(data, response_text)

                logger.info(
                    f"VLM 调用成功: model={model}, response_len={len(response_text)}, "
                    f"confidence={confidence:.2f}, elapsed={elapsed:.2f}s"
                )

                return response_text, confidence

            except httpx.HTTPStatusError as e:
                last_exception = e
                logger.warning(
                    f"VLM HTTP 错误: status={e.response.status_code}, "
                    f"retry={retry_count}/{max_retries}"
                )
            except httpx.TimeoutException as e:
                last_exception = e
                logger.warning(
                    f"VLM 请求超时: timeout={timeout}s, retry={retry_count}/{max_retries}"
                )
            except httpx.RequestError as e:
                last_exception = e
                logger.warning(
                    f"VLM 请求错误: {e}, retry={retry_count}/{max_retries}"
                )
            except (KeyError, json.JSONDecodeError) as e:
                last_exception = e
                logger.warning(f"VLM 响应解析错误: {e}, retry={retry_count}/{max_retries}")

            # 重试前等待（指数退避）
            retry_count += 1
            if retry_count <= max_retries:
                backoff = 0.5 * (2 ** (retry_count - 1))  # 0.5s, 1s, 2s, ...
                logger.info(f"等待 {backoff}s 后重试...")
                await asyncio.sleep(backoff)

    # 重试次数用尽
    error_msg = f"VLM 调用失败，重试 {max_retries} 次后仍失败: {last_exception}"
    logger.error(error_msg)
    raise VLMError(error_msg) from last_exception


def _extract_confidence(response_data: dict, response_text: str) -> float:
    """
    从响应数据中提取置信度。

    优先从响应中解析 confidence 字段；若无，则根据文本是否为空计算：
    - 非空文本：0.9
    - 空文本：0.1

    Args:
        response_data: VLM 响应的 JSON 数据。
        response_text: 提取的响应文本。

    Returns:
        float: 置信度（0~1）。
    """
    # 尝试从响应顶层提取 confidence
    if "confidence" in response_data:
        try:
            conf = float(response_data["confidence"])
            return max(0.0, min(1.0, conf))  # 限制在 0~1
        except (TypeError, ValueError):
            pass

    # 尝试从 choices[0] 中提取
    choices = response_data.get("choices", [])
    if choices and isinstance(choices, list):
        choice = choices[0]
        if isinstance(choice, dict) and "confidence" in choice:
            try:
                conf = float(choice["confidence"])
                return max(0.0, min(1.0, conf))
            except (TypeError, ValueError):
                pass

    # 尝试从响应文本中解析 JSON 并提取 confidence
    if response_text:
        try:
            parsed = json.loads(response_text)
            if isinstance(parsed, dict) and "confidence" in parsed:
                conf = float(parsed["confidence"])
                return max(0.0, min(1.0, conf))
        except (json.JSONDecodeError, TypeError, ValueError):
            pass

    # 默认置信度计算
    if response_text and len(response_text) > 0:
        return 0.9
    else:
        return 0.1


if __name__ == "__main__":
    import argparse
    import base64

    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    async def test():
        """测试入口：调用 VLM 服务并打印结果。"""
        parser = argparse.ArgumentParser(description="VLM 客户端测试")
        parser.add_argument("--image", required=True, help="测试图片路径")
        parser.add_argument(
            "--prompt", default="提取图片中的所有文字内容", help="用户提示词"
        )
        parser.add_argument(
            "--endpoint",
            default="https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions",
            help="VLM 服务端点",
        )
        parser.add_argument("--model", default="qwen3-vl-plus", help="模型名称")
        parser.add_argument("--api-key", default="sk-eb0a0c50ab534cf0bd991859558edbf2", help="API 密钥")
        parser.add_argument("--timeout", type=float, default=30.0, help="超时秒数")
        parser.add_argument("--max-retries", type=int, default=2, help="最大重试次数")
        args = parser.parse_args()

        try:
            # 读取图片并编码为 base64
            with open(args.image, "rb") as f:
                image_bytes = f.read()
            b64_encoded = base64.b64encode(image_bytes).decode("utf-8")
            image_base64 = f"data:image/jpeg;base64,{b64_encoded}"

            print(f"图片大小: {len(image_bytes)} bytes")
            print(f"Base64 长度: {len(image_base64)}")
            print(f"端点: {args.endpoint}")
            print(f"模型: {args.model}")
            print("-" * 50)

            # 调用 VLM
            response, confidence = await call_vlm(
                image_base64=image_base64,
                user_prompt=args.prompt,
                endpoint=args.endpoint,
                model=args.model,
                api_key=args.api_key,
                timeout=args.timeout,
                max_retries=args.max_retries,
            )

            print(f"响应: {response}")
            print(f"置信度: {confidence:.2f}")

        except FileNotFoundError:
            print(f"错误: 找不到图片文件 {args.image}")
        except VLMError as e:
            print(f"VLM 调用错误: {e}")
        except Exception as e:
            print(f"未知错误: {e}")

    asyncio.run(test())
