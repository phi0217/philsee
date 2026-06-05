"""
应用配置管理

使用 Pydantic Settings 从环境变量加载配置。
"""

from typing import Any, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """应用配置类"""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # VLM 配置
    vlm_endpoint: str
    vlm_model: str
    vlm_api_key: str
    vlm_max_tokens: Optional[int] = None  # -1 或空表示不限制
    vlm_temperature: float = 0.0
    vlm_timeout: float = 30.0
    vlm_max_retries: int = 2
    vlm_enable_thinking: bool = False

    # MinIO 配置
    minio_endpoint: str
    minio_access_key: str
    minio_secret_key: str
    minio_bucket: str
    minio_secure: bool = False

    # MySQL 配置
    mysql_host: str
    mysql_port: int = 3306
    mysql_user: str
    mysql_password: str
    mysql_database: str

    # 图像预处理配置
    image_target_short_edge: int = 1024

    # 应用配置
    debug: bool = False
    app_name: str = "Philsee Document Parser"

    def get_db_url(self) -> str:
        """构建数据库连接 URL"""
        return (
            f"mysql+aiomysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
        )

    def get_vlm_config(self) -> dict[str, Any]:
        """获取 VLM 配置"""
        return {
            "endpoint": self.vlm_endpoint,
            "model": self.vlm_model,
            "api_key": self.vlm_api_key,
            "max_tokens": self.vlm_max_tokens if self.vlm_max_tokens and self.vlm_max_tokens > 0 else None,
            "temperature": self.vlm_temperature,
            "timeout": self.vlm_timeout,
            "max_retries": self.vlm_max_retries,
            "enable_thinking": self.vlm_enable_thinking,
        }

    def get_minio_config(self) -> dict[str, Any]:
        """获取 MinIO 配置"""
        return {
            "endpoint": self.minio_endpoint,
            "access_key": self.minio_access_key,
            "secret_key": self.minio_secret_key,
            "bucket": self.minio_bucket,
            "secure": self.minio_secure,
        }


# 全局配置实例
settings = Settings()
