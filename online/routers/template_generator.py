"""
模板自动生成路由

POST /generate_template - 自动生成模板配置
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import JSONResponse

from online.processors.image_preprocess import preprocess_image, encode_to_base64
from online.services.template_generator_service import (
    generate_template,
    TemplateGeneratorError,
    ConflictError,
)
from online.core.database import async_session_factory
from online.api.deps import get_vlm_config

logger = logging.getLogger(__name__)

router = APIRouter(prefix="", tags=["Template Generator"])


@router.post("/generate_template")
async def generate_template_endpoint(
    files: list[UploadFile] = File(..., description="单据所有页面图片（按页码顺序上传）"),
    doc_type: str = Form(..., description="文档类型（如 invoice, letter_of_credit）"),
    template_id: Optional[str] = Form(None, description="模板业务编号（可选，不提供则自动生成）"),
    version: Optional[str] = Form(None, description="模板版本号（可选，如 v1.0.0）"),
) -> JSONResponse:
    """
    自动生成模板配置。

    接收一份完整单据的所有页面图片（按页码顺序）以及 doc_type，
    调用 VLM 自动分析图片，生成 fields、profile、aggregation 三套配置，
    并自动将配置插入 config_versions 表，将模板插入 config_templates 表，
    返回新创建的模板信息。

    重要约束：
    - 所有插入 config_versions 表的记录，其 version_tag 字段直接使用最终的 template_id
    - 如果 (doc_type, config_type, version_tag) 发生唯一冲突，返回 409 错误
    - template_id 若未提供，自动生成：{doc_type}_default_{timestamp}

    Args:
        files: 图片文件列表（至少一张）。
        doc_type: 文档类型（必须）。
        template_id: 模板业务编号（可选）。
        version: 模板版本号（可选）。

    Returns:
        JSONResponse: 成功时返回模板信息，失败时返回错误信息。
    """
    # 参数校验
    if not files or len(files) == 0:
        return JSONResponse(
            status_code=400,
            content={"error": "必须上传至少一张图片"},
        )

    if not doc_type:
        return JSONResponse(
            status_code=400,
            content={"error": "必须提供 doc_type 参数"},
        )

    logger.info(
        f"开始生成模板: doc_type={doc_type}, files={len(files)}, "
        f"template_id={template_id}, version={version}"
    )

    try:
        # 1. 读取并预处理所有图片
        async def process_upload_image(upload_file: UploadFile, idx: int) -> str:
            """读取并预处理单个图片，返回 base64"""
            raw_bytes = await upload_file.read()
            processed = preprocess_image(raw_bytes, 1024)
            return encode_to_base64(processed)

        process_tasks = [process_upload_image(f, idx) for idx, f in enumerate(files)]
        images_base64 = await asyncio.gather(*process_tasks)

        logger.info(f"图片预处理完成: {len(images_base64)} 张")

        # 2. 获取配置
        vlm_config = get_vlm_config()

        # 3. 调用服务生成模板
        async with async_session_factory() as session:
            result = await generate_template(
                session=session,
                images_base64=images_base64,
                doc_type=doc_type,
                template_id=template_id,
                version=version,
                vlm_config=vlm_config,
            )

        logger.info(f"模板生成成功: template_id={result['template_id']}")

        return JSONResponse(
            status_code=200,
            content=result,
        )

    except ConflictError as e:
        logger.warning(f"模板冲突: {e}")
        return JSONResponse(
            status_code=409,
            content={"error": str(e)},
        )

    except TemplateGeneratorError as e:
        logger.error(f"模板生成失败: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"模板生成失败: {e}"},
        )

    except Exception as e:
        logger.exception(f"未知错误: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"处理失败: {e}"},
        )
