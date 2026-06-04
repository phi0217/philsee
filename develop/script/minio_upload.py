"""
MinIO 异步上传模块

实现异步上传图片到 MinIO 对象存储的功能。
使用 asyncio.to_thread 将同步操作包装为异步，避免阻塞事件循环。
"""

import asyncio
import io
import logging
import mimetypes
import os
import sys
from typing import Optional

from minio import Minio
from minio.error import S3Error

# 配置日志
logger = logging.getLogger(__name__)


class MinioUploadError(Exception):
    """MinIO 上传异常"""

    pass


async def upload_to_minio(
    image_bytes: bytes,
    bucket: str,
    object_name: str,
    endpoint: str,
    access_key: str,
    secret_key: str,
    secure: bool = False,
    region: Optional[str] = None
) -> str:
    """
    异步上传图片到 MinIO 对象存储。

    将图片 bytes 上传到指定桶，返回对象路径（bucket/object_name）。
    使用 asyncio.to_thread 将同步操作包装为异步。

    Args:
        image_bytes: 图片的原始字节数据
        bucket: 存储桶名称
        object_name: 对象名称（例如 trace_id/page_1.jpg）
        endpoint: MinIO 服务端点（如 localhost:9000）
        access_key: 访问密钥
        secret_key: 秘密密钥
        secure: 是否使用 HTTPS，默认 False
        region: 可选区域，默认 None

    Returns:
        str: 对象路径，格式：{bucket}/{object_name}

    Raises:
        MinioUploadError: 上传失败时抛出
    """
    try:
        # 创建 MinIO 客户端（同步）
        client = Minio(
            endpoint,
            access_key=access_key,
            secret_key=secret_key,
            secure=secure,
            region=region
        )

        # 检查桶是否存在，若不存在则自动创建
        bucket_exists = await asyncio.to_thread(client.bucket_exists, bucket)
        if not bucket_exists:
            logger.info(f"桶 {bucket} 不存在，正在创建...")
            await asyncio.to_thread(client.make_bucket, bucket)
            logger.info(f"桶 {bucket} 创建成功")

        # 根据 object_name 获取 Content-Type
        content_type = _get_content_type(object_name)

        # 构造 BytesIO 对象
        data = io.BytesIO(image_bytes)
        data_length = len(image_bytes)

        # 使用 asyncio.to_thread 执行上传
        await asyncio.to_thread(
            client.put_object,
            bucket,
            object_name,
            data,
            data_length,
            content_type=content_type
        )

        object_path = f"{bucket}/{object_name}"
        logger.info(f"上传成功: {object_path}")
        return object_path

    except S3Error as e:
        error_msg = f"MinIO S3 错误: {e}"
        logger.error(error_msg)
        raise MinioUploadError(error_msg) from e
    except Exception as e:
        error_msg = f"上传失败: {e}"
        logger.error(error_msg)
        raise MinioUploadError(error_msg) from e


def _get_content_type(object_name: str) -> str:
    """
    根据文件名获取 Content-Type。

    Args:
        object_name: 对象名称

    Returns:
        str: Content-Type 字符串
    """
    # 尝试根据文件扩展名推断
    mime_type, _ = mimetypes.guess_type(object_name)
    if mime_type and mime_type.startswith("image/"):
        return mime_type

    # 默认返回 image/jpeg
    return "image/jpeg"


async def upload_file_to_minio(
    file_path: str,
    bucket: str,
    object_name: str,
    endpoint: str,
    access_key: str,
    secret_key: str,
    secure: bool = False,
    region: Optional[str] = None
) -> str:
    """
    异步上传本地图片文件到 MinIO 对象存储。

    Args:
        file_path: 本地图片文件路径
        bucket: 存储桶名称
        object_name: 对象名称
        endpoint: MinIO 服务端点
        access_key: 访问密钥
        secret_key: 秘密密钥
        secure: 是否使用 HTTPS，默认 False
        region: 可选区域，默认 None

    Returns:
        str: 对象路径

    Raises:
        MinioUploadError: 上传失败时抛出
        FileNotFoundError: 文件不存在时抛出
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"文件不存在: {file_path}")

    with open(file_path, "rb") as f:
        image_bytes = f.read()

    return await upload_to_minio(
        image_bytes=image_bytes,
        bucket=bucket,
        object_name=object_name,
        endpoint=endpoint,
        access_key=access_key,
        secret_key=secret_key,
        secure=secure,
        region=region
    )


if __name__ == "__main__":
    import argparse

    # 配置日志
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )

    async def test():
        """
        测试入口：从命令行读取本地图片文件路径和 MinIO 连接信息，
        执行上传并打印结果。
        """
        parser = argparse.ArgumentParser(description="上传图片到 MinIO")
        parser.add_argument("image_path", help="本地图片文件路径")
        parser.add_argument("--bucket", default="test-bucket", help="存储桶名称")
        parser.add_argument("--object-name", default=None, help="对象名称（默认使用文件名）")
        args = parser.parse_args()

        # 从环境变量获取 MinIO 连接信息
        endpoint = os.getenv("MINIO_ENDPOINT", "localhost:9000")
        access_key = os.getenv("MINIO_ACCESS_KEY", "admin")
        secret_key = os.getenv("MINIO_SECRET_KEY", "admin123456")
        secure = os.getenv("MINIO_SECURE", "false").lower() == "true"

        # 确定对象名称
        object_name = args.object_name or os.path.basename(args.image_path)

        try:
            path = await upload_file_to_minio(
                file_path=args.image_path,
                bucket=args.bucket,
                object_name=object_name,
                endpoint=endpoint,
                access_key=access_key,
                secret_key=secret_key,
                secure=secure
            )
            print(f"上传成功: {path}")
        except FileNotFoundError as e:
            print(f"错误: {e}")
            sys.exit(1)
        except MinioUploadError as e:
            print(f"上传失败: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"未知错误: {e}")
            sys.exit(1)

    asyncio.run(test())
