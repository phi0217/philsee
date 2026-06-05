"""
FastAPI 应用入口

整合所有模块，提供 /parse 端点用于处理单据解析请求。
支持多图片上传，异步处理，完整的错误处理和日志记录。

v2.0 更新：
- 支持配置模板化
- 支持按权重分流
- 记录分流决策追踪信息
"""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

# 导入各模块
from online.aggregator import aggregate_results
from online.config_loader import load_config, ConfigLoadError
from online.db_writer import save_results, create_tables, DatabaseWriterError
from online.field_extractor import FieldExtractionError
from online.image_preprocess import encode_to_base64, preprocess_image
from online.minio_upload import upload_to_minio, MinioUploadError
from online.page_processor import process_page
from online.pipeline import execute_pre_process_pipeline
from online.trace_manager import TraceManager
from online.routers import template_generator

# 加载 .env 文件
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
)
logger = logging.getLogger(__name__)


class AppConfig:
    """应用配置类"""

    def __init__(self):
        """从环境变量加载配置"""
        # VLM 配置
        self.vlm_endpoint = self._get_required_env("VLM_ENDPOINT")
        self.vlm_model = self._get_required_env("VLM_MODEL")
        self.vlm_api_key = self._get_required_env("VLM_API_KEY")
        # max_tokens: -1 或空表示不限制
        max_tokens_str = os.getenv("VLM_MAX_TOKENS", "-1").strip()
        self.vlm_max_tokens = None if max_tokens_str in ("-1", "", "none", "None") else int(max_tokens_str)
        self.vlm_temperature = float(os.getenv("VLM_TEMPERATURE", "0.0"))
        self.vlm_timeout = float(os.getenv("VLM_TIMEOUT", "30.0"))
        self.vlm_max_retries = int(os.getenv("VLM_MAX_RETRIES", "2"))
        self.vlm_enable_thinking = os.getenv("VLM_ENABLE_THINKING", "false").lower() == "true"

        # MinIO 配置
        self.minio_endpoint = self._get_required_env("MINIO_ENDPOINT")
        self.minio_access_key = self._get_required_env("MINIO_ACCESS_KEY")
        self.minio_secret_key = self._get_required_env("MINIO_SECRET_KEY")
        self.minio_bucket = self._get_required_env("MINIO_BUCKET")
        self.minio_secure = os.getenv("MINIO_SECURE", "false").lower() == "true"

        # MySQL 配置
        self.mysql_host = self._get_required_env("MYSQL_HOST")
        self.mysql_port = os.getenv("MYSQL_PORT", "3306")
        self.mysql_user = self._get_required_env("MYSQL_USER")
        self.mysql_password = self._get_required_env("MYSQL_PASSWORD")
        self.mysql_database = self._get_required_env("MYSQL_DATABASE")

        # 图像预处理配置
        self.image_target_short_edge = int(os.getenv("IMAGE_TARGET_SHORT_EDGE", "1024"))

    def _get_required_env(self, key: str) -> str:
        """获取必需的环境变量，不存在则抛出异常"""
        value = os.getenv(key)
        if value is None:
            raise ValueError(f"缺少必需的环境变量: {key}")
        return value

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


# 全局配置
config: Optional[AppConfig] = None

# 全局资源
trace_manager = TraceManager()
db_engine = None
async_session = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    global db_engine, async_session, config

    logger.info("应用启动中...")

    # 加载配置
    try:
        config = AppConfig()
        logger.info("配置加载成功")
    except ValueError as e:
        logger.error(f"配置加载失败: {e}")
        raise

    # 创建数据库引擎
    db_url = config.get_db_url()
    db_engine = create_async_engine(db_url, echo=False, pool_pre_ping=True)
    async_session = async_sessionmaker(db_engine, expire_on_commit=False)

    # 创建表（如果不存在）
    try:
        await create_tables(db_engine, dialect="mysql")
        logger.info("数据库表检查完成")
    except Exception as e:
        logger.warning(f"创建表时出错（可能已存在）: {e}")

    logger.info("应用启动完成")

    yield

    # 关闭资源
    if db_engine:
        await db_engine.dispose()
    logger.info("应用关闭完成")


# 创建 FastAPI 应用
app = FastAPI(
    title="Philsee Document Parser",
    version="2.0.0",
    description="智能单据解析服务 - 支持配置模板化与分流决策追踪",
    lifespan=lifespan,
)

# 注册路由
app.include_router(template_generator.router)


def _get_fields_for_page(
    profile: dict[str, Any],
    fields_schema: dict[str, Any],
    page_num: int,
    total_pages: int,
) -> list[dict[str, Any]]:
    """
    获取指定页面需要提取的字段列表。

    根据 profile 中的 pages 属性过滤当前页需要提取的字段。

    Args:
        profile: 字段策略配置。
        fields_schema: 全局字段定义。
        page_num: 当前页码（从1开始）。
        total_pages: 总页数。

    Returns:
        list[dict]: 该页需要提取的字段配置列表。
    """
    fields_for_page = []
    profile_fields = profile.get("fields", {})

    for field_name, field_cfg in profile_fields.items():
        pages_cfg = field_cfg.get("pages", "all")

        # 判断该字段是否需要在当前页提取
        should_extract = False

        if pages_cfg == "all":
            should_extract = True
        elif pages_cfg == "first" and page_num == 1:
            should_extract = True
        elif pages_cfg == "last" and page_num == total_pages:
            should_extract = True
        elif isinstance(pages_cfg, list) and page_num in pages_cfg:
            should_extract = True

        if should_extract:
            # 合并 fields_schema 中的类型信息
            field_type = fields_schema.get(field_name, {}).get("type", "string")
            prompt_hint = field_cfg.get("prompt_hint", fields_schema.get(field_name, {}).get("description", ""))

            full_cfg = {
                "field_name": field_name,
                "type": field_type,
                "prompt_hint": prompt_hint,
                **{k: v for k, v in field_cfg.items() if k not in ("pages", "field_name", "type", "prompt_hint")},
            }
            fields_for_page.append(full_cfg)

    return fields_for_page


@app.post("/parse")
async def parse_document(
    doc_type: Optional[str] = Form(None, description="单据类型（与 template_id 至少填一个）"),
    template_id: Optional[str] = Form(None, description="模板编号（优先级高于 doc_type）"),
    images: list[UploadFile] = File(..., description="图片文件列表"),
) -> JSONResponse:
    """
    解析单据文档。

    接收单据类型和多个图片文件，执行以下操作：
    1. 生成 trace_id
    2. 预处理所有图片
    3. 解析模板并加载配置（支持按权重分流）
    4. 逐页提取字段
    5. 聚合结果
    6. 存储到数据库（包含分流决策追踪）

    Args:
        doc_type: 单据类型（如 "letter_of_credit"）。
        template_id: 模板编号（如 "lc_extraction"），优先级高于 doc_type。
        images: 图片文件列表。

    Returns:
        JSONResponse: 解析结果或错误信息。
    """
    # 参数校验
    if doc_type is None and template_id is None:
        return JSONResponse(
            status_code=400,
            content={"error": "必须提供 doc_type 或 template_id 参数"},
        )

    # 生成 trace_id
    trace_id = trace_manager.new_trace()
    start_time = time.monotonic()

    logger.info(
        f"[{trace_id}] 开始处理请求: doc_type={doc_type}, template_id={template_id}, images={len(images)}"
    )

    try:
        # 更新状态
        trace_manager.update_state(trace_id, {"status": "preprocessing", "doc_type": doc_type})

        # 1. 读取原始图片
        async def read_upload_image(upload_file: UploadFile, idx: int) -> bytes:
            """读取单个上传的图片"""
            raw_bytes = await upload_file.read()
            return raw_bytes

        read_tasks = [read_upload_image(img, idx) for idx, img in enumerate(images)]
        raw_images = await asyncio.gather(*read_tasks)

        logger.info(f"[{trace_id}] 图片读取完成: {len(raw_images)} 张")

        # 2. 加载配置（通过模板方式）- 提前加载以获取 pre_process
        trace_manager.update_state(trace_id, {"status": "loading_config"})

        async with async_session() as session:
            loaded_config = await load_config(
                session=session,
                doc_type=doc_type,
                template_id=template_id,
            )

        fields_schema = loaded_config["fields_schema"]
        profile = loaded_config["profile"]
        agg_rules = loaded_config["agg_rules"]
        template_info = loaded_config["template"]
        resolve_trace = loaded_config["trace"]
        pre_process_pipeline = template_info.get("pre_process", "")

        logger.info(
            f"[{trace_id}] 配置加载完成: template={template_info['template_id']}@{template_info['version']}"
        )

        # 3. 预处理所有图片（包含前处理管道和标准预处理）
        trace_manager.update_state(trace_id, {"status": "preprocessing"})

        async def process_upload_image(raw_bytes: bytes, idx: int) -> tuple[bytes, str, str]:
            """处理单个图片：前处理管道 -> 标准预处理 -> base64编码"""
            # 执行前处理管道（如果有配置）
            if pre_process_pipeline:
                try:
                    processed = execute_pre_process_pipeline(raw_bytes, pre_process_pipeline)
                    logger.debug(f"[{trace_id}] 第 {idx + 1} 页前处理管道完成")
                except ValueError as e:
                    logger.warning(f"[{trace_id}] 第 {idx + 1} 页前处理管道失败: {e}，使用原图")
                    processed = raw_bytes
            else:
                processed = raw_bytes

            # 执行标准预处理（缩放）
            processed = preprocess_image(processed, config.image_target_short_edge)

            # 编码为 base64
            b64 = encode_to_base64(processed)
            return processed, b64, f"page_{idx + 1}.jpg"

        preprocess_tasks = [
            process_upload_image(raw_bytes, idx) for idx, raw_bytes in enumerate(raw_images)
        ]
        processed_results = await asyncio.gather(*preprocess_tasks)

        processed_images = [r[0] for r in processed_results]
        base64_list = [r[1] for r in processed_results]
        object_names = [r[2] for r in processed_results]

        logger.info(f"[{trace_id}] 图片预处理完成: {len(processed_images)} 张")

        # 4. 上传到 MinIO（并行）
        trace_manager.update_state(trace_id, {"status": "uploading"})

        async def upload_single_image(image_bytes: bytes, obj_name: str) -> str:
            """上传单张图片到 MinIO"""
            return await upload_to_minio(
                image_bytes=image_bytes,
                bucket=config.minio_bucket,
                object_name=f"{trace_id}/{obj_name}",
                endpoint=config.minio_endpoint,
                access_key=config.minio_access_key,
                secret_key=config.minio_secret_key,
                secure=config.minio_secure,
            )

        upload_tasks = [
            upload_single_image(img, obj_name)
            for img, obj_name in zip(processed_images, object_names)
        ]
        minio_paths = await asyncio.gather(*upload_tasks)

        logger.info(f"[{trace_id}] MinIO 上传完成: {len(minio_paths)} 张")

        # 4. 逐页提取字段（串行，利用前缀缓存）
        trace_manager.update_state(trace_id, {"status": "extracting"})

        vlm_config = config.get_vlm_config()
        total_pages = len(base64_list)
        all_page_results: list[list[dict[str, Any]]] = []

        for page_num, (b64, minio_path) in enumerate(zip(base64_list, minio_paths), start=1):
            # 获取该页需要提取的字段
            fields_for_page = _get_fields_for_page(profile, fields_schema, page_num, total_pages)

            if not fields_for_page:
                logger.info(f"[{trace_id}] 第 {page_num} 页无需提取字段，跳过")
                continue

            logger.info(f"[{trace_id}] 第 {page_num} 页提取 {len(fields_for_page)} 个字段")

            # 调用 process_page 提取
            page_results = await process_page(
                image_base64=b64,
                fields_config=fields_for_page,
                page_num=page_num,
                vlm_config=vlm_config,
            )

            # 添加 page 和 minio_path 信息
            for result in page_results:
                result["page"] = page_num
                result["minio_path"] = minio_path

            all_page_results.append(page_results)

            # 更新状态
            trace_manager.update_state(trace_id, {"current_page": page_num})

        logger.info(f"[{trace_id}] 字段提取完成: {len(all_page_results)} 页")

        # 5. 聚合结果
        trace_manager.update_state(trace_id, {"status": "aggregating"})

        final_fields, agg_decisions = aggregate_results(all_page_results, agg_rules)

        logger.info(f"[{trace_id}] 聚合完成: {len(final_fields)} 个字段")

        # 6. 存储到数据库
        trace_manager.update_state(trace_id, {"status": "saving"})

        warnings: list[dict[str, Any]] = []

        async with async_session() as session:
            await save_results(
                session=session,
                trace_id=trace_id,
                doc_type=doc_type or template_info.get("doc_type", "unknown"),
                total_pages=total_pages,
                final_fields=final_fields,
                warnings=warnings,
                page_results=all_page_results,
                agg_decisions=agg_decisions,
                template_id=template_info["template_id"],
                template_version=template_info["version"],
                selected_weight=template_info["weight"],
                resolve_trace=resolve_trace,
            )

        logger.info(f"[{trace_id}] 数据库存储完成")

        # 完成
        elapsed = time.monotonic() - start_time
        trace_manager.update_state(trace_id, {"status": "completed", "elapsed": elapsed})

        logger.info(f"[{trace_id}] 请求处理完成: elapsed={elapsed:.2f}s")

        return JSONResponse(
            status_code=200,
            content={
                "trace_id": trace_id,
                "fields": final_fields,
                "warnings": warnings,
                "template": template_info,
                "elapsed": round(elapsed, 2),
            },
        )

    except ConfigLoadError as e:
        elapsed = time.monotonic() - start_time
        logger.error(f"[{trace_id}] 配置加载失败: {e}")
        trace_manager.update_state(trace_id, {"status": "error", "error": str(e)})
        return JSONResponse(
            status_code=500,
            content={"trace_id": trace_id, "error": f"配置加载失败: {e}"},
        )

    except MinioUploadError as e:
        elapsed = time.monotonic() - start_time
        logger.error(f"[{trace_id}] MinIO 上传失败: {e}")
        trace_manager.update_state(trace_id, {"status": "error", "error": str(e)})
        return JSONResponse(
            status_code=500,
            content={"trace_id": trace_id, "error": f"图片上传失败: {e}"},
        )

    except FieldExtractionError as e:
        elapsed = time.monotonic() - start_time
        logger.error(f"[{trace_id}] 字段提取失败: {e}")
        trace_manager.update_state(trace_id, {"status": "error", "error": str(e)})
        return JSONResponse(
            status_code=500,
            content={"trace_id": trace_id, "error": f"字段提取失败: {e}"},
        )

    except DatabaseWriterError as e:
        elapsed = time.monotonic() - start_time
        logger.error(f"[{trace_id}] 数据库写入失败: {e}")
        trace_manager.update_state(trace_id, {"status": "error", "error": str(e)})
        return JSONResponse(
            status_code=500,
            content={"trace_id": trace_id, "error": f"数据库写入失败: {e}"},
        )

    except Exception as e:
        elapsed = time.monotonic() - start_time
        logger.exception(f"[{trace_id}] 未知错误: {e}")
        trace_manager.update_state(trace_id, {"status": "error", "error": str(e)})
        return JSONResponse(
            status_code=500,
            content={"trace_id": trace_id, "error": f"处理失败: {e}"},
        )


@app.get("/health")
async def health_check():
    """健康检查端点"""
    return {"status": "healthy", "traces_count": trace_manager.count()}


@app.get("/state/{trace_id}")
async def get_trace_state(trace_id: str):
    """获取请求状态"""
    state = trace_manager.get_state(trace_id)
    if not state:
        raise HTTPException(status_code=404, detail="trace_id not found")
    return {"trace_id": trace_id, "state": state}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("online.main_api:app", host="0.0.0.0", port=port, reload=True)
