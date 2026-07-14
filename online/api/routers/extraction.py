"""
文档解析路由模块

提供 /parse 端点用于处理文档解析请求。
路由层只做参数校验和响应组装，业务编排下沉到 ExtractionService。
"""

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from online.api.deps import get_vlm_config, get_minio_config, get_image_config, get_trace_mgr
from online.services.extraction_service import process_document, ExtractionServiceError

logger = logging.getLogger(__name__)

router = APIRouter(tags=["extraction"])


@router.post("/parse")
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

    if not images:
        return JSONResponse(
            status_code=400,
            content={"error": "必须上传至少一张图片"},
        )

    logger.info(
        f"开始处理请求: doc_type={doc_type}, template_id={template_id}, images={len(images)}"
    )

    try:
        # 读取原始图片
        async def read_upload_image(upload_file: UploadFile) -> bytes:
            return await upload_file.read()

        read_tasks = [read_upload_image(img) for img in images]
        raw_images = await asyncio.gather(*read_tasks)

        logger.info(f"图片读取完成: {len(raw_images)} 张")

        # 调用 ExtractionService 执行完整解析流程
        result = await process_document(
            images=raw_images,
            doc_type=doc_type,
            template_id=template_id,
            vlm_config=get_vlm_config(),
            minio_config=get_minio_config(),
            image_config=get_image_config(),
            trace_manager=get_trace_mgr(),
        )

        return JSONResponse(status_code=200, content=result)

    except ExtractionServiceError as e:
        logger.error(f"文档解析失败: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)},
        )

    except Exception as e:
        logger.exception(f"未知错误: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": f"处理失败: {e}"},
        )