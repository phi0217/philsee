"""
MinIO 异步上传模块（兼容层）

此文件保留用于向后兼容，实际代码已迁移至 processors/minio_upload.py。
"""

from online.processors.minio_upload import upload_to_minio, upload_file_to_minio, MinioUploadError

__all__ = ["upload_to_minio", "upload_file_to_minio", "MinioUploadError"]