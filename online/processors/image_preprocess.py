"""
图像预处理模块

将原始图片缩放到指定的短边长度（保持宽高比），输出 JPEG 格式（质量 85），
并转换为 base64 字符串（带 data URL 前缀）。
"""

import base64
import logging

import cv2
import numpy as np

logger = logging.getLogger(__name__)


def preprocess_image(image_bytes: bytes, target_short_edge: int = 1024) -> bytes:
    """
    将原始图片缩放到指定的短边长度，保持宽高比。

    Args:
        image_bytes: 原始图片的字节数据。
        target_short_edge: 目标短边长度，默认为 1024 像素。

    Returns:
        缩放后的图片字节数据（JPEG 格式，质量 85）。

    Raises:
        ValueError: 如果图片格式不支持或无法解码。
    """
    # 将 bytes 转换为 numpy 数组
    nparr = np.frombuffer(image_bytes, np.uint8)

    # 解码图片
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
    if img is None:
        logger.error("Failed to decode image: unsupported format or corrupted data")
        raise ValueError("无法解码图片：格式不支持或数据损坏")

    # 获取原始尺寸
    original_height, original_width = img.shape[:2]
    logger.info(f"Original image size: {original_width}x{original_height}")

    # 计算短边
    short_edge = min(original_width, original_height)

    # 如果短边已经小于等于目标值，不需要放大，只缩小
    if short_edge <= target_short_edge:
        # 计算缩放比例
        scale = target_short_edge / short_edge
        new_width = int(original_width * scale)
        new_height = int(original_height * scale)
    else:
        # 如果短边大于目标值，需要缩小
        scale = target_short_edge / short_edge
        new_width = int(original_width * scale)
        new_height = int(original_height * scale)

    # 执行缩放
    resized_img = cv2.resize(img, (new_width, new_height), interpolation=cv2.INTER_AREA)

    logger.info(f"Resized image size: {new_width}x{new_height}")

    # 编码为 JPEG（质量 85）
    encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), 85]
    success, encoded = cv2.imencode('.jpg', resized_img, encode_params)

    if not success:
        logger.error("Failed to encode image to JPEG format")
        raise ValueError("无法将图片编码为 JPEG 格式")

    # 转换为 bytes
    result_bytes = encoded.tobytes()

    return result_bytes


def encode_to_base64(image_bytes: bytes) -> str:
    """
    将图片字节数据编码为 base64 字符串（带 data URL 前缀）。

    Args:
        image_bytes: 图片的字节数据。

    Returns:
        data URL 格式的 base64 字符串（格式：data:image/jpeg;base64,<base64>）。
    """
    # 进行 base64 编码
    b64_encoded = base64.b64encode(image_bytes).decode('utf-8')

    # 拼接 data URL 前缀
    data_url = f"data:image/jpeg;base64,{b64_encoded}"

    return data_url
