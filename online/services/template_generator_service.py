"""
模板自动生成服务

接收单据图片，调用 VLM 自动生成 fields、profile、aggregation 配置，
并插入数据库，返回新创建的模板信息。
"""

import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.exc import IntegrityError

from online.vlm_client import call_vlm, VLMError
from online.image_preprocess import preprocess_image, encode_to_base64
from online.utils.version_helper import (
    generate_default_template_id,
    generate_template_version,
    check_config_version_exists,
    insert_config_version,
    check_template_exists,
    insert_template,
)
from online.utils.validator import (
    validate_fields_config,
    validate_profile_config,
    validate_aggregation_config,
    extract_profile_field_names,
    ConfigValidationError,
)

logger = logging.getLogger(__name__)


class TemplateGeneratorError(Exception):
    """模板生成异常"""

    pass


class ConflictError(Exception):
    """唯一约束冲突异常"""

    pass


# ============================================================
# VLM 提示词模板
# ============================================================

FIELDS_SYSTEM_PROMPT = """你是一个专业的单据字段分析专家。你的任务是分析提供的图片，识别出单据中所有可能需要提取的字段，并生成字段定义配置。

输出要求：
1. 必须输出有效的 JSON 格式
2. JSON 结构必须包含 "fields" 对象
3. 每个字段必须包含 "type" 属性（string/number/date/list/object/boolean）
4. 可选包含 "description" 属性描述字段含义
5. 不要输出任何 JSON 之外的额外文字

示例输出格式：
{
  "fields": {
    "invoice_number": {
      "type": "string",
      "description": "发票号码"
    },
    "amount": {
      "type": "number",
      "description": "金额"
    }
  }
}"""

FIELDS_USER_PROMPT_TEMPLATE = """请分析以下 {page_count} 张图片，这是一份完整单据的所有页面。
请识别单据中所有可能需要提取的字段，生成全局字段定义 JSON。
字段类型包括：string（字符串）、number（数字）、date（日期）、list（列表）、object（对象）、boolean（布尔）。

注意：
1. 综合所有页面分析，不要遗漏任何页面中的字段
2. 字段命名使用英文下划线风格（如 invoice_number）
3. 为每个字段提供清晰的中文描述"""

PROFILE_SYSTEM_PROMPT = """你是一个专业的单据字段策略配置专家。你的任务是根据单据图片和字段定义，生成字段提取策略配置。

输出要求：
1. 必须输出有效的 JSON 格式
2. JSON 必须包含 "doc_type" 和 "fields" 字段
3. 每个字段可以包含：
   - "prompt_hint": 提取提示词
   - "pages": 指定在哪页提取（"all"/"first"/"last"/[1,2,3]）
   - "post_process": 后处理管道（可选）
4. 不要输出任何 JSON 之外的额外文字

示例输出格式：
{
  "doc_type": "invoice",
  "fields": {
    "invoice_number": {
      "prompt_hint": "提取发票号码，通常位于发票右上角",
      "pages": "first"
    },
    "total_amount": {
      "prompt_hint": "提取总金额，通常在表格底部",
      "pages": "last"
    }
  }
}"""

PROFILE_USER_PROMPT_TEMPLATE = """请根据以下 {page_count} 张图片和已定义的字段，生成字段提取策略配置。

文档类型：{doc_type}

已定义的字段：
{fields_json}

要求：
1. 为每个字段提供提取提示词（prompt_hint），描述字段位置和识别方法
2. 根据字段在单据中的位置，指定 pages 属性：
   - "all": 所有页面都需要提取（默认）
   - "first": 只在第一页提取
   - "last": 只在最后一页提取
   - [1,2,3]: 在指定页码提取
3. doc_type 必须是: {doc_type}"""

AGGREGATION_SYSTEM_PROMPT = """你是一个专业的数据聚合策略专家。你的任务是根据字段定义和提取策略，生成多页字段聚合规则配置。

输出要求：
1. 必须输出有效的 JSON 格式
2. JSON 必须包含 "fields" 对象
3. 每个字段可以指定聚合策略：
   - "first": 取第一个非空值
   - "last": 取最后一个非空值
   - "concat": 拼接所有值
   - "max": 取最大值（数值类型）
   - "min": 取最小值（数值类型）
   - "sum": 求和（数值类型）
   - "latest": 取最新日期
   - "earliest": 取最早日期
4. 不要输出任何 JSON 之外的额外文字

示例输出格式：
{
  "fields": {
    "invoice_number": {
      "strategy": "first"
    },
    "item_description": {
      "strategy": "concat",
      "separator": "\\n"
    }
  }
}"""

AGGREGATION_USER_PROMPT_TEMPLATE = """请根据以下字段列表，生成聚合策略配置。

字段列表：{field_names}

要求：
1. 根据字段特点选择合适的聚合策略
2. 对于标识性字段（如单据编号），使用 "first" 策略
3. 对于明细字段（如商品描述），使用 "concat" 策略
4. 对于数值汇总字段，使用 "sum" 策略
5. 默认策略为 "first" """


# ============================================================
# 核心服务函数
# ============================================================


async def generate_template(
    session: AsyncSession,
    images_base64: list[str],
    doc_type: str,
    template_id: str | None,
    version: str | None,
    vlm_config: dict[str, Any],
) -> dict[str, Any]:
    """
    自动生成模板配置。

    核心步骤：
    1. 确定最终 template_id
    2. 调用 VLM 生成 fields 配置
    3. 调用 VLM 生成 profile 配置
    4. 调用 VLM 生成 aggregation 配置
    5. 创建模板记录
    6. 返回结果

    Args:
        session: SQLAlchemy 异步会话。
        images_base64: 图片 base64 列表（已包含 data URL 前缀）。
        doc_type: 文档类型。
        template_id: 可选，模板 ID。
        version: 可选，版本号。
        vlm_config: VLM 配置。

    Returns:
        dict: 生成的模板信息。

    Raises:
        ConflictError: 唯一约束冲突。
        TemplateGeneratorError: 生成失败。
    """
    page_count = len(images_base64)
    logger.info(f"开始生成模板: doc_type={doc_type}, pages={page_count}")

    # 1. 确定最终 template_id
    final_template_id = template_id or generate_default_template_id(doc_type)
    logger.info(f"使用 template_id: {final_template_id}")

    # 2. 检查 fields 配置是否已存在
    if await check_config_version_exists(session, "*", "fields", final_template_id):
        raise ConflictError(f"template_id '{final_template_id}' 已存在（fields 配置冲突），请更换 template_id")

    try:
        # 3. 调用 VLM 生成 fields 配置
        fields_config = await generate_fields_config(
            images_base64=images_base64,
            vlm_config=vlm_config,
        )
        logger.info(f"fields 配置生成成功: {len(fields_config.get('fields', {}))} 个字段")

        # 4. 插入 fields 配置
        fields_config_id = await insert_config_version(
            session=session,
            doc_type="*",
            config_type="fields",
            version_tag=final_template_id,
            content=fields_config,
            created_by="system",
        )
        logger.info(f"fields 配置已插入: id={fields_config_id}")

        # 5. 检查 profile 配置是否已存在
        if await check_config_version_exists(session, doc_type, "profile", final_template_id):
            raise ConflictError(f"template_id '{final_template_id}' 已存在（profile 配置冲突）")

        # 6. 调用 VLM 生成 profile 配置
        profile_config = await generate_profile_config(
            images_base64=images_base64,
            doc_type=doc_type,
            fields_config=fields_config,
            vlm_config=vlm_config,
        )
        logger.info(f"profile 配置生成成功: {len(profile_config.get('fields', {}))} 个字段")

        # 7. 插入 profile 配置
        profile_config_id = await insert_config_version(
            session=session,
            doc_type=doc_type,
            config_type="profile",
            version_tag=final_template_id,
            content=profile_config,
            created_by="system",
        )
        logger.info(f"profile 配置已插入: id={profile_config_id}")

        # 8. 检查 aggregation 配置是否已存在
        if await check_config_version_exists(session, doc_type, "aggregation", final_template_id):
            raise ConflictError(f"template_id '{final_template_id}' 已存在（aggregation 配置冲突）")

        # 9. 调用 VLM 生成 aggregation 配置
        profile_field_names = extract_profile_field_names(profile_config)
        aggregation_config = await generate_aggregation_config(
            profile_field_names=profile_field_names,
            vlm_config=vlm_config,
        )
        logger.info(f"aggregation 配置生成成功: {len(aggregation_config.get('fields', {}))} 个字段规则")

        # 10. 插入 aggregation 配置
        aggregation_config_id = await insert_config_version(
            session=session,
            doc_type=doc_type,
            config_type="aggregation",
            version_tag=final_template_id,
            content=aggregation_config,
            created_by="system",
        )
        logger.info(f"aggregation 配置已插入: id={aggregation_config_id}")

        # 11. 生成模板版本号
        template_version = await generate_template_version(session, final_template_id, version)
        logger.info(f"使用模板版本: {template_version}")

        # 12. 检查模板是否已存在
        if await check_template_exists(session, final_template_id, template_version):
            raise ConflictError(f"模板 '{final_template_id}@{template_version}' 已存在")

        # 13. 创建模板记录
        description = f"Auto-generated from {page_count} sample pages"
        template_db_id = await insert_template(
            session=session,
            template_id=final_template_id,
            version=template_version,
            doc_type=doc_type,
            fields_config_id=fields_config_id,
            profile_config_id=profile_config_id,
            aggregation_config_id=aggregation_config_id,
            description=description,
            pre_process="",
            created_by="system",
        )
        logger.info(f"模板记录已创建: id={template_db_id}")

        # 14. 提交事务
        await session.commit()
        logger.info(f"模板生成完成: template_id={final_template_id}, version={template_version}")

        return {
            "template_id": final_template_id,
            "template_version": template_version,
            "doc_type": doc_type,
            "fields_config_id": fields_config_id,
            "profile_config_id": profile_config_id,
            "aggregation_config_id": aggregation_config_id,
            "message": "Template created successfully",
        }

    except IntegrityError as e:
        await session.rollback()
        error_msg = str(e.orig) if hasattr(e, 'orig') else str(e)
        logger.error(f"唯一约束冲突: {error_msg}")
        raise ConflictError(f"模板或配置已存在: {error_msg}")

    except (ConflictError, TemplateGeneratorError):
        await session.rollback()
        raise

    except Exception as e:
        await session.rollback()
        logger.error(f"模板生成失败: {e}")
        raise TemplateGeneratorError(f"模板生成失败: {e}") from e


async def generate_fields_config(
    images_base64: list[str],
    vlm_config: dict[str, Any],
) -> dict[str, Any]:
    """
    调用 VLM 生成 fields 配置。

    综合所有图片，生成全局字段定义 JSON。

    Args:
        images_base64: 图片 base64 列表。
        vlm_config: VLM 配置。

    Returns:
        dict: fields 配置。

    Raises:
        TemplateGeneratorError: 生成失败。
    """
    page_count = len(images_base64)

    # 构建多图片消息内容
    message_content = []
    for b64 in images_base64:
        message_content.append({
            "type": "image_url",
            "image_url": {"url": b64},
        })

    # 添加提示词
    user_prompt = FIELDS_USER_PROMPT_TEMPLATE.format(page_count=page_count)
    message_content.append({
        "type": "text",
        "text": user_prompt,
    })

    try:
        # 调用 VLM（使用自定义系统提示词）
        response_text, _ = await _call_vlm_with_images(
            images_base64=images_base64,
            user_prompt=user_prompt,
            system_prompt=FIELDS_SYSTEM_PROMPT,
            vlm_config=vlm_config,
        )

        # 解析 JSON
        config = _parse_json_response(response_text)

        # 校验配置
        is_valid, error_msg = validate_fields_config(config)
        if not is_valid:
            raise TemplateGeneratorError(f"fields 配置校验失败: {error_msg}")

        return config

    except VLMError as e:
        raise TemplateGeneratorError(f"VLM 调用失败: {e}") from e


async def generate_profile_config(
    images_base64: list[str],
    doc_type: str,
    fields_config: dict[str, Any],
    vlm_config: dict[str, Any],
) -> dict[str, Any]:
    """
    调用 VLM 生成 profile 配置。

    基于所有图片和 fields，生成 profile JSON。

    Args:
        images_base64: 图片 base64 列表。
        doc_type: 文档类型。
        fields_config: fields 配置。
        vlm_config: VLM 配置。

    Returns:
        dict: profile 配置。

    Raises:
        TemplateGeneratorError: 生成失败。
    """
    page_count = len(images_base64)
    fields_json = json.dumps(fields_config.get("fields", {}), ensure_ascii=False, indent=2)

    user_prompt = PROFILE_USER_PROMPT_TEMPLATE.format(
        page_count=page_count,
        doc_type=doc_type,
        fields_json=fields_json,
    )

    try:
        # 调用 VLM
        response_text, _ = await _call_vlm_with_images(
            images_base64=images_base64,
            user_prompt=user_prompt,
            system_prompt=PROFILE_SYSTEM_PROMPT,
            vlm_config=vlm_config,
        )

        # 解析 JSON
        config = _parse_json_response(response_text)

        # 校验配置
        is_valid, error_msg = validate_profile_config(config, doc_type)
        if not is_valid:
            raise TemplateGeneratorError(f"profile 配置校验失败: {error_msg}")

        return config

    except VLMError as e:
        raise TemplateGeneratorError(f"VLM 调用失败: {e}") from e


async def generate_aggregation_config(
    profile_field_names: list[str],
    vlm_config: dict[str, Any],
) -> dict[str, Any]:
    """
    调用 VLM 生成 aggregation 配置。

    基于 profile 中的字段列表，生成聚合策略 JSON。

    Args:
        profile_field_names: profile 中的字段名列表。
        vlm_config: VLM 配置。

    Returns:
        dict: aggregation 配置。

    Raises:
        TemplateGeneratorError: 生成失败。
    """
    user_prompt = AGGREGATION_USER_PROMPT_TEMPLATE.format(
        field_names=", ".join(profile_field_names),
    )

    try:
        # 调用 VLM（不需要图片）
        response_text, _ = await call_vlm(
            image_base64="",  # 空图片
            user_prompt=user_prompt,
            system_prompt=AGGREGATION_SYSTEM_PROMPT,
            endpoint=vlm_config["endpoint"],
            model=vlm_config["model"],
            api_key=vlm_config["api_key"],
            max_tokens=vlm_config.get("max_tokens"),
            temperature=vlm_config.get("temperature", 0.0),
            max_retries=vlm_config.get("max_retries", 2),
            timeout=vlm_config.get("timeout", 30.0),
        )

        # 解析 JSON
        config = _parse_json_response(response_text)

        # 校验配置
        is_valid, error_msg = validate_aggregation_config(config, profile_field_names)
        if not is_valid:
            raise TemplateGeneratorError(f"aggregation 配置校验失败: {error_msg}")

        return config

    except VLMError as e:
        raise TemplateGeneratorError(f"VLM 调用失败: {e}") from e


async def _call_vlm_with_images(
    images_base64: list[str],
    user_prompt: str,
    system_prompt: str,
    vlm_config: dict[str, Any],
) -> tuple[str, float]:
    """
    调用 VLM 处理多张图片。

    Args:
        images_base64: 图片 base64 列表。
        user_prompt: 用户提示词。
        system_prompt: 系统提示词。
        vlm_config: VLM 配置。

    Returns:
        tuple[str, float]: (响应文本, 置信度)。
    """
    import httpx

    # 构建消息内容
    message_content = []
    for b64 in images_base64:
        message_content.append({
            "type": "image_url",
            "image_url": {"url": b64},
        })
    message_content.append({
        "type": "text",
        "text": user_prompt,
    })

    # 构建请求体
    request_body = {
        "model": vlm_config["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": message_content},
        ],
        "temperature": vlm_config.get("temperature", 0.0),
    }

    if vlm_config.get("max_tokens"):
        request_body["max_tokens"] = vlm_config["max_tokens"]

    # 构建请求头
    headers = {"Content-Type": "application/json"}
    if vlm_config.get("api_key"):
        headers["Authorization"] = f"Bearer {vlm_config['api_key']}"

    # 发送请求
    timeout = vlm_config.get("timeout", 60.0)
    async with httpx.AsyncClient(timeout=timeout) as client:
        response = await client.post(
            vlm_config["endpoint"],
            json=request_body,
            headers=headers,
        )
        response.raise_for_status()

        data = response.json()
        response_text = data["choices"][0]["message"]["content"]
        response_text = response_text.strip() if response_text else ""

        # 提取置信度
        confidence = 0.9 if response_text else 0.1

        return response_text, confidence


def _parse_json_response(response_text: str) -> dict[str, Any]:
    """
    解析 VLM 响应中的 JSON。

    尝试从响应文本中提取 JSON 对象。

    Args:
        response_text: VLM 响应文本。

    Returns:
        dict: 解析后的 JSON 对象。

    Raises:
        TemplateGeneratorError: 解析失败。
    """
    try:
        # 尝试直接解析
        return json.loads(response_text)
    except json.JSONDecodeError:
        pass

    # 尝试提取 JSON 代码块
    import re

    # 尝试提取 ```json ... ``` 或 ``` ... ```
    pattern = r"```(?:json)?\s*\n?(.*?)\n?```"
    matches = re.findall(pattern, response_text, re.DOTALL)

    for match in matches:
        try:
            return json.loads(match.strip())
        except json.JSONDecodeError:
            continue

    # 尝试找到第一个 { 和最后一个 }
    start = response_text.find("{")
    end = response_text.rfind("}")

    if start != -1 and end != -1 and end > start:
        try:
            return json.loads(response_text[start : end + 1])
        except json.JSONDecodeError:
            pass

    raise TemplateGeneratorError(f"无法从响应中解析 JSON: {response_text[:200]}...")
