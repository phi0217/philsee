"""
文档解析服务模块

封装文档解析的核心编排逻辑，将路由层的处理流程下沉到 Service 层。
"""

import asyncio
import logging
import time
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from online.core.database import async_session_factory
from online.core.trace_manager import TraceManager
from online.services.config_service import load_config, ConfigLoadError
from online.services.db_service import save_results, create_tables, DatabaseWriterError
from online.services.aggregator_service import aggregate_results
from online.processors.field_extractor import FieldExtractionError
from online.processors.image_preprocess import encode_to_base64, preprocess_image
from online.processors.minio_upload import upload_to_minio, MinioUploadError
from online.processors.page_processor import process_page
from online.processors.pipeline import execute_pre_process_pipeline

logger = logging.getLogger(__name__)


class ExtractionServiceError(Exception):
    """文档解析服务异常"""
    pass


class ExtractionService:
    """
    文档解析服务。

    封装完整的文档解析编排流程，包括：
    1. 配置加载
    2. 图片预处理
    3. MinIO 上传
    4. 字段提取
    5. 结果聚合
    6. 数据持久化
    """

    def __init__(
        self,
        session: AsyncSession,
        trace_manager: TraceManager,
        vlm_config: dict[str, Any],
        minio_config: dict[str, Any],
        image_config: dict[str, Any],
    ):
        self.session = session
        self.trace_manager = trace_manager
        self.vlm_config = vlm_config
        self.minio_config = minio_config
        self.image_config = image_config

    def _get_fields_for_page(
        self,
        profile: dict[str, Any],
        fields_schema: dict[str, Any],
        page_num: int,
        total_pages: int,
    ) -> list[dict[str, Any]]:
        """
        获取指定页面需要提取的字段列表。

        Args:
            profile: 字段策略配置
            fields_schema: 全局字段定义
            page_num: 当前页码（从1开始）
            total_pages: 总页数

        Returns:
            该页需要提取的字段配置列表
        """
        fields_for_page = []
        profile_fields = profile.get("fields", {})

        for field_name, field_cfg in profile_fields.items():
            pages_cfg = field_cfg.get("pages", "all")

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

    async def process(
        self,
        images: list[bytes],
        doc_type: Optional[str],
        template_id: Optional[str],
    ) -> dict[str, Any]:
        """
        执行完整的文档解析流程。

        Args:
            images: 原始图片字节数据列表
            doc_type: 文档类型
            template_id: 模板编号

        Returns:
            dict: {
                "trace_id": str,
                "fields": dict,
                "warnings": list,
                "template": dict,
                "elapsed": float,
            }

        Raises:
            ExtractionServiceError: 解析过程中发生错误
        """
        trace_id = self.trace_manager.new_trace()
        start_time = time.monotonic()

        logger.info(
            f"[{trace_id}] 开始处理请求: doc_type={doc_type}, template_id={template_id}, images={len(images)}"
        )

        try:
            # 1. 加载配置
            self.trace_manager.update_state(trace_id, {"status": "loading_config"})
            loaded_config = await load_config(
                session=self.session,
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

            # 2. 图片预处理（含前处理管道 + 标准缩放 + base64编码）
            self.trace_manager.update_state(trace_id, {"status": "preprocessing"})

            async def process_single_image(raw_bytes: bytes, idx: int) -> tuple[bytes, str, str]:
                if pre_process_pipeline:
                    try:
                        processed = execute_pre_process_pipeline(raw_bytes, pre_process_pipeline)
                    except ValueError as e:
                        logger.warning(f"[{trace_id}] 第 {idx + 1} 页前处理管道失败: {e}，使用原图")
                        processed = raw_bytes
                else:
                    processed = raw_bytes

                processed = preprocess_image(processed, self.image_config["target_short_edge"])
                b64 = encode_to_base64(processed)
                return processed, b64, f"page_{idx + 1}.jpg"

            preprocess_tasks = [process_single_image(img, idx) for idx, img in enumerate(images)]
            processed_results = await asyncio.gather(*preprocess_tasks)

            processed_images = [r[0] for r in processed_results]
            base64_list = [r[1] for r in processed_results]
            object_names = [r[2] for r in processed_results]

            logger.info(f"[{trace_id}] 图片预处理完成: {len(processed_images)} 张")

            # 3. 上传到 MinIO
            self.trace_manager.update_state(trace_id, {"status": "uploading"})

            async def upload_single_image(image_bytes: bytes, obj_name: str) -> str:
                return await upload_to_minio(
                    image_bytes=image_bytes,
                    bucket=self.minio_config["bucket"],
                    object_name=f"{trace_id}/{obj_name}",
                    endpoint=self.minio_config["endpoint"],
                    access_key=self.minio_config["access_key"],
                    secret_key=self.minio_config["secret_key"],
                    secure=self.minio_config["secure"],
                )

            upload_tasks = [
                upload_single_image(img, obj_name)
                for img, obj_name in zip(processed_images, object_names)
            ]
            minio_paths = await asyncio.gather(*upload_tasks)

            logger.info(f"[{trace_id}] MinIO 上传完成: {len(minio_paths)} 张")

            # 4. 逐页提取字段（串行）
            self.trace_manager.update_state(trace_id, {"status": "extracting"})

            total_pages = len(base64_list)
            all_page_results: list[list[dict[str, Any]]] = []

            for page_num, (b64, minio_path) in enumerate(zip(base64_list, minio_paths), start=1):
                fields_for_page = self._get_fields_for_page(profile, fields_schema, page_num, total_pages)
                if not fields_for_page:
                    logger.info(f"[{trace_id}] 第 {page_num} 页无需提取字段，跳过")
                    continue

                page_results = await process_page(
                    image_base64=b64,
                    fields_config=fields_for_page,
                    page_num=page_num,
                    vlm_config=self.vlm_config,
                )

                for result in page_results:
                    result["page"] = page_num
                    result["minio_path"] = minio_path

                all_page_results.append(page_results)
                self.trace_manager.update_state(trace_id, {"current_page": page_num})

            logger.info(f"[{trace_id}] 字段提取完成: {len(all_page_results)} 页")

            # 5. 聚合结果
            self.trace_manager.update_state(trace_id, {"status": "aggregating"})
            final_fields, agg_decisions = aggregate_results(all_page_results, agg_rules)
            logger.info(f"[{trace_id}] 聚合完成: {len(final_fields)} 个字段")

            # 6. 存储到数据库
            self.trace_manager.update_state(trace_id, {"status": "saving"})

            warnings: list[dict[str, Any]] = []
            await save_results(
                session=self.session,
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
            self.trace_manager.update_state(trace_id, {"status": "completed", "elapsed": elapsed})

            logger.info(f"[{trace_id}] 请求处理完成: elapsed={elapsed:.2f}s")

            return {
                "trace_id": trace_id,
                "fields": final_fields,
                "warnings": warnings,
                "template": template_info,
                "elapsed": round(elapsed, 2),
            }

        except (ConfigLoadError, MinioUploadError, FieldExtractionError, DatabaseWriterError) as e:
            elapsed = time.monotonic() - start_time
            logger.error(f"[{trace_id}] 处理失败: {e}")
            self.trace_manager.update_state(trace_id, {"status": "error", "error": str(e)})
            raise ExtractionServiceError(str(e)) from e

        except Exception as e:
            elapsed = time.monotonic() - start_time
            logger.exception(f"[{trace_id}] 未知错误: {e}")
            self.trace_manager.update_state(trace_id, {"status": "error", "error": str(e)})
            raise ExtractionServiceError(f"处理失败: {e}") from e


async def process_document(
    images: list[bytes],
    doc_type: Optional[str],
    template_id: Optional[str],
    vlm_config: dict[str, Any],
    minio_config: dict[str, Any],
    image_config: dict[str, Any],
    trace_manager: Optional[TraceManager] = None,
) -> dict[str, Any]:
    """
    文档解析的便捷函数（供路由层调用）。

    Args:
        images: 原始图片字节数据列表
        doc_type: 文档类型
        template_id: 模板编号
        vlm_config: VLM 配置
        minio_config: MinIO 配置
        image_config: 图像处理配置
        trace_manager: 可选的追踪管理器实例

    Returns:
        dict: 解析结果
    """
    if trace_manager is None:
        from online.core.trace_manager import get_trace_manager
        trace_manager = get_trace_manager()

    async with async_session_factory() as session:
        service = ExtractionService(
            session=session,
            trace_manager=trace_manager,
            vlm_config=vlm_config,
            minio_config=minio_config,
            image_config=image_config,
        )
        return await service.process(images, doc_type, template_id)