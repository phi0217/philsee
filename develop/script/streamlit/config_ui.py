"""
Streamlit 配置管理工具 - 通用文档解析系统 (philsee)

v2.0 更新：
- 配置模板化管理
- 支持按权重分流
- 移除 config_versions 表的 is_active 字段管理
- 新增模板管理功能
"""

import json
import os
import logging
from datetime import datetime
from typing import Any, Optional

import pymysql
from pymysql.cursors import DictCursor
import streamlit as st

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 数据库连接配置（可通过环境变量覆盖）
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': int(os.getenv('DB_PORT', 3306)),
    'user': os.getenv('DB_USER', 'root'),
    'password': os.getenv('DB_PASSWORD', 'password'),
    'database': os.getenv('DB_NAME', 'philsee'),
    'charset': 'utf8mb4',
}


def get_db_connection() -> pymysql.Connection:
    """
    获取 MySQL 数据库连接。

    Returns:
        pymysql.Connection: 数据库连接对象，使用字典游标。

    Raises:
        pymysql.Error: 数据库连接失败时抛出异常。
    """
    try:
        connection = pymysql.connect(
            **DB_CONFIG,
            cursorclass=DictCursor
        )
        logger.info("数据库连接成功")
        return connection
    except pymysql.Error as e:
        logger.error(f"数据库连接失败: {e}")
        raise


# ============================================================
# 配置版本相关函数
# ============================================================

def get_all_config_versions() -> list[dict[str, Any]]:
    """
    获取所有配置版本列表。

    Returns:
        list[dict]: 配置版本列表。
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = """
                SELECT id, version_tag, doc_type, config_type, content, created_at, created_by
                FROM config_versions
                WHERE is_deleted = 0
                ORDER BY id DESC
            """
            cursor.execute(sql)
            return cursor.fetchall()
    except pymysql.Error as e:
        logger.error(f"获取配置版本列表失败: {e}")
        return []
    finally:
        conn.close()


def get_config_versions_by_type(doc_type: str, config_type: str) -> list[dict[str, Any]]:
    """
    获取指定类型的配置版本列表。

    Args:
        doc_type: 文档类型。
        config_type: 配置类型。

    Returns:
        list[dict]: 配置版本列表。
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = """
                SELECT id, version_tag, doc_type, config_type, content, created_at, created_by
                FROM config_versions
                WHERE doc_type = %s AND config_type = %s AND is_deleted = 0
                ORDER BY id DESC
            """
            cursor.execute(sql, (doc_type, config_type))
            return cursor.fetchall()
    except pymysql.Error as e:
        logger.error(f"获取配置版本列表失败: {e}")
        return []
    finally:
        conn.close()


def save_config_version(
    doc_type: str,
    config_type: str,
    content: dict,
    version_tag: str,
    created_by: str
) -> tuple[bool, str]:
    """
    保存配置版本。

    Args:
        doc_type: 文档类型。
        config_type: 配置类型。
        content: 配置内容。
        version_tag: 版本标签。
        created_by: 创建者。

    Returns:
        tuple[bool, str]: (是否成功, 消息)。
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = """
                INSERT INTO config_versions
                (version_tag, doc_type, config_type, content, created_at, created_by, is_deleted)
                VALUES (%s, %s, %s, %s, %s, %s, 0)
            """
            cursor.execute(sql, (
                version_tag,
                doc_type,
                config_type,
                json.dumps(content, ensure_ascii=False),
                datetime.now(),
                created_by
            ))
        conn.commit()
        logger.info(f"保存配置版本成功: {doc_type}/{config_type}@{version_tag}")
        return True, f"版本 {version_tag} 保存成功！"
    except pymysql.Error as e:
        logger.error(f"保存配置版本失败: {e}")
        return False, f"保存失败: {str(e)}"
    finally:
        conn.close()


def delete_config_version(version_id: int) -> tuple[bool, str]:
    """
    软删除配置版本。

    Args:
        version_id: 配置版本 ID。

    Returns:
        tuple[bool, str]: (是否成功, 消息)。
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 检查是否被模板引用
            check_sql = """
                SELECT COUNT(*) as cnt FROM config_templates
                WHERE (fields_config_id = %s OR profile_config_id = %s OR aggregation_config_id = %s)
                  AND is_active = 1
            """
            cursor.execute(check_sql, (version_id, version_id, version_id))
            result = cursor.fetchone()
            if result['cnt'] > 0:
                return False, "该配置版本被激活的模板引用，无法删除"

            # 软删除
            sql = "UPDATE config_versions SET is_deleted = 1 WHERE id = %s"
            cursor.execute(sql, (version_id,))
        conn.commit()
        return True, "配置版本已删除"
    except pymysql.Error as e:
        logger.error(f"删除配置版本失败: {e}")
        return False, f"删除失败: {str(e)}"
    finally:
        conn.close()


# ============================================================
# 模板管理相关函数
# ============================================================

def get_all_templates() -> list[dict[str, Any]]:
    """
    获取所有模板列表。

    Returns:
        list[dict]: 模板列表。
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = """
                SELECT t.id, t.template_id, t.version, t.doc_type, t.description,
                       t.fields_config_id, t.profile_config_id, t.aggregation_config_id,
                       t.pre_process, t.is_active, t.weight, t.created_at, t.created_by, t.updated_at, t.updated_by
                FROM config_templates t
                ORDER BY t.template_id, t.version DESC
            """
            cursor.execute(sql)
            return cursor.fetchall()
    except pymysql.Error as e:
        logger.error(f"获取模板列表失败: {e}")
        return []
    finally:
        conn.close()


def get_templates_grouped() -> dict[str, list[dict[str, Any]]]:
    """
    获取按 template_id 分组的模板列表。

    Returns:
        dict[str, list]: 分组的模板列表。
    """
    templates = get_all_templates()
    grouped = {}
    for t in templates:
        tid = t['template_id']
        if tid not in grouped:
            grouped[tid] = []
        grouped[tid].append(t)
    return grouped


def get_template_weight_summary(template_id: str) -> dict[str, Any]:
    """
    获取指定模板 ID 的权重汇总信息。

    Args:
        template_id: 模板编号。

    Returns:
        dict: 包含 total_weight, active_count, warning 等信息。
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = """
                SELECT COALESCE(SUM(weight), 0) as total_weight, COUNT(*) as active_count
                FROM config_templates
                WHERE template_id = %s AND is_active = 1
            """
            cursor.execute(sql, (template_id,))
            result = cursor.fetchone()

            total_weight = result['total_weight']
            warning = None
            if total_weight != 100:
                warning = f"权重总和为 {total_weight}，建议调整为 100"

            return {
                'total_weight': total_weight,
                'active_count': result['active_count'],
                'warning': warning
            }
    except pymysql.Error as e:
        logger.error(f"获取权重汇总失败: {e}")
        return {'total_weight': 0, 'active_count': 0, 'warning': '获取失败'}
    finally:
        conn.close()


def save_template(
    template_id: str,
    version: str,
    doc_type: str,
    description: str,
    fields_config_id: int,
    profile_config_id: int,
    aggregation_config_id: int,
    pre_process: str,
    is_active: bool,
    weight: int,
    created_by: str
) -> tuple[bool, str]:
    """
    保存新模板。

    Args:
        template_id: 模板编号。
        version: 模板版本。
        doc_type: 文档类型。
        description: 模板说明。
        fields_config_id: 字段配置 ID。
        profile_config_id: 字段策略配置 ID。
        aggregation_config_id: 聚合规则配置 ID。
        pre_process: 前处理管道。
        is_active: 是否激活。
        weight: 权重。
        created_by: 创建者。

    Returns:
        tuple[bool, str]: (是否成功, 消息)。
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            # 检查是否已存在
            check_sql = "SELECT id FROM config_templates WHERE template_id = %s AND version = %s"
            cursor.execute(check_sql, (template_id, version))
            if cursor.fetchone():
                return False, f"模板 {template_id}@{version} 已存在"

            sql = """
                INSERT INTO config_templates
                (template_id, version, doc_type, description,
                 fields_config_id, profile_config_id, aggregation_config_id, pre_process,
                 is_active, weight, created_at, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """
            cursor.execute(sql, (
                template_id, version, doc_type, description,
                fields_config_id, profile_config_id, aggregation_config_id, pre_process,
                is_active, weight, datetime.now(), created_by
            ))
        conn.commit()
        logger.info(f"保存模板成功: {template_id}@{version}")
        return True, f"模板 {template_id}@{version} 保存成功！"
    except pymysql.Error as e:
        logger.error(f"保存模板失败: {e}")
        return False, f"保存失败: {str(e)}"
    finally:
        conn.close()


def update_template(
    template_id: str,
    version: str,
    description: Optional[str] = None,
    pre_process: Optional[str] = None,
    is_active: Optional[bool] = None,
    weight: Optional[int] = None,
    updated_by: str = "streamlit"
) -> tuple[bool, str]:
    """
    更新模板信息。

    Args:
        template_id: 模板编号。
        version: 模板版本。
        description: 模板说明。
        pre_process: 前处理管道。
        is_active: 是否激活。
        weight: 权重。
        updated_by: 更新者。

    Returns:
        tuple[bool, str]: (是否成功, 消息)。
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            updates = []
            params = []

            if description is not None:
                updates.append("description = %s")
                params.append(description)
            if pre_process is not None:
                updates.append("pre_process = %s")
                params.append(pre_process)
            if is_active is not None:
                updates.append("is_active = %s")
                params.append(is_active)
            if weight is not None:
                updates.append("weight = %s")
                params.append(weight)

            if not updates:
                return False, "没有要更新的字段"

            updates.append("updated_by = %s")
            updates.append("updated_at = %s")
            params.extend([updated_by, datetime.now()])
            params.extend([template_id, version])

            sql = f"""
                UPDATE config_templates
                SET {', '.join(updates)}
                WHERE template_id = %s AND version = %s
            """
            cursor.execute(sql, params)
        conn.commit()
        return True, "模板更新成功"
    except pymysql.Error as e:
        logger.error(f"更新模板失败: {e}")
        return False, f"更新失败: {str(e)}"
    finally:
        conn.close()


def delete_template(template_id: str, version: str) -> tuple[bool, str]:
    """
    删除模板。

    Args:
        template_id: 模板编号。
        version: 模板版本。

    Returns:
        tuple[bool, str]: (是否成功, 消息)。
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = "DELETE FROM config_templates WHERE template_id = %s AND version = %s"
            cursor.execute(sql, (template_id, version))
        conn.commit()
        return True, "模板已删除"
    except pymysql.Error as e:
        logger.error(f"删除模板失败: {e}")
        return False, f"删除失败: {str(e)}"
    finally:
        conn.close()


def get_config_version_options(config_type: str) -> list[dict[str, Any]]:
    """
    获取配置版本选项列表（用于下拉选择）。

    Args:
        config_type: 配置类型。

    Returns:
        list[dict]: 配置版本选项列表。
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = """
                SELECT id, version_tag, doc_type
                FROM config_versions
                WHERE config_type = %s AND is_deleted = 0
                ORDER BY id DESC
            """
            cursor.execute(sql, (config_type,))
            results = cursor.fetchall()
            return [
                {
                    'id': r['id'],
                    'label': f"{r['version_tag']} ({r['doc_type']})"
                }
                for r in results
            ]
    except pymysql.Error as e:
        logger.error(f"获取配置版本选项失败: {e}")
        return []
    finally:
        conn.close()


# ============================================================
# Streamlit 界面
# ============================================================

def render_config_versions_tab():
    """渲染配置版本管理选项卡"""
    st.header("📋 配置版本管理")
    st.markdown("管理 fields、profile、aggregation 三种类型的配置版本。")

    # 筛选条件
    col1, col2 = st.columns(2)
    with col1:
        filter_doc_type = st.text_input("文档类型筛选", value="", placeholder="留空显示全部")
    with col2:
        filter_config_type = st.selectbox("配置类型筛选", ["全部", "fields", "profile", "aggregation"])

    # 获取配置列表
    all_configs = get_all_config_versions()

    # 筛选
    if filter_doc_type:
        all_configs = [c for c in all_configs if c['doc_type'] == filter_doc_type]
    if filter_config_type != "全部":
        all_configs = [c for c in all_configs if c['config_type'] == filter_config_type]

    # 展示配置列表
    if all_configs:
        for config in all_configs:
            with st.container(border=True):
                col1, col2, col3, col4 = st.columns([2, 2, 2, 1])

                with col1:
                    st.markdown(f"**ID:** {config['id']}")
                    st.markdown(f"**版本:** `{config['version_tag']}`")
                with col2:
                    st.markdown(f"**文档类型:** `{config['doc_type']}`")
                    st.markdown(f"**配置类型:** `{config['config_type']}`")
                with col3:
                    st.markdown(f"**创建者:** {config['created_by'] or '-'}")
                    created_time = config['created_at'].strftime("%Y-%m-%d %H:%M") if config['created_at'] else "-"
                    st.markdown(f"**时间:** {created_time}")
                with col4:
                    if st.button("🗑️", key=f"del_config_{config['id']}", help="删除"):
                        success, msg = delete_config_version(config['id'])
                        if success:
                            st.success(msg)
                            st.rerun()
                        else:
                            st.error(msg)

                # 展示配置内容
                with st.expander("查看配置内容"):
                    st.json(config['content'])
    else:
        st.info("暂无配置版本数据")

    st.divider()

    # 新增配置版本
    st.subheader("➕ 新增配置版本")

    col1, col2 = st.columns(2)
    with col1:
        new_doc_type = st.text_input("文档类型", value="*", placeholder="如: invoice, letter_of_credit, *")
        new_config_type = st.selectbox("配置类型", ["fields", "profile", "aggregation"], key="new_config_type")
    with col2:
        new_version_tag = st.text_input("版本标签", value="v1.0.0", placeholder="如: v1.0.0")
        new_created_by = st.text_input("创建者", value="streamlit")

    new_content = st.text_area(
        "配置内容 (JSON)",
        value="{}",
        height=200,
        key="new_config_content"
    )

    if st.button("💾 保存配置版本", type="primary"):
        if not new_version_tag.strip():
            st.error("版本标签不能为空")
        else:
            try:
                parsed_content = json.loads(new_content)
            except json.JSONDecodeError as e:
                st.error(f"JSON 格式错误: {e}")
            else:
                success, msg = save_config_version(
                    doc_type=new_doc_type or "*",
                    config_type=new_config_type,
                    content=parsed_content,
                    version_tag=new_version_tag.strip(),
                    created_by=new_created_by.strip() or "streamlit"
                )
                if success:
                    st.success(msg)
                    st.rerun()
                else:
                    st.error(msg)


def render_templates_tab():
    """渲染模板管理选项卡"""
    st.header("🔧 模板管理")
    st.markdown("管理配置模板，支持按权重分流。")

    # 获取分组后的模板
    grouped_templates = get_templates_grouped()

    if grouped_templates:
        for template_id, versions in grouped_templates.items():
            with st.container(border=True):
                # 模板 ID 标题
                st.subheader(f"📦 {template_id}")

                # 获取权重汇总
                weight_summary = get_template_weight_summary(template_id)

                # 权重状态显示
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("激活版本数", weight_summary['active_count'])
                with col2:
                    st.metric("权重总和", weight_summary['total_weight'])
                with col3:
                    if weight_summary['warning']:
                        st.warning(weight_summary['warning'])
                    else:
                        st.success("权重配置正确 ✅")

                # 展示各版本
                for v in versions:
                    with st.expander(f"{v['version']} {'✅ 激活' if v['is_active'] else '⚪ 未激活'} - 权重: {v['weight']}"):
                        col1, col2 = st.columns([3, 1])
                        with col1:
                            st.markdown(f"**文档类型:** `{v['doc_type']}`")
                            st.markdown(f"**描述:** {v['description'] or '-'}")
                            st.markdown(f"**前处理管道:** `{v.get('pre_process', '') or '-'}`")
                            st.markdown(f"**配置 ID:** fields={v['fields_config_id']}, profile={v['profile_config_id']}, agg={v['aggregation_config_id']}")
                            st.markdown(f"**创建者:** {v['created_by'] or '-'} | **更新者:** {v['updated_by'] or '-'}")
                        with col2:
                            # 编辑按钮
                            if st.button("✏️ 编辑", key=f"edit_{v['template_id']}_{v['version']}"):
                                st.session_state['edit_template'] = {
                                    'template_id': v['template_id'],
                                    'version': v['version'],
                                    'description': v['description'] or '',
                                    'pre_process': v.get('pre_process', '') or '',
                                    'is_active': v['is_active'],
                                    'weight': v['weight']
                                }

                            # 删除按钮
                            if st.button("🗑️ 删除", key=f"del_{v['template_id']}_{v['version']}"):
                                success, msg = delete_template(v['template_id'], v['version'])
                                if success:
                                    st.success(msg)
                                    st.rerun()
                                else:
                                    st.error(msg)

                st.divider()
    else:
        st.info("暂无模板数据")

    # 编辑弹窗
    if 'edit_template' in st.session_state:
        st.divider()
        st.subheader("✏️ 编辑模板")
        edit_data = st.session_state['edit_template']

        st.markdown(f"**模板:** `{edit_data['template_id']}` @ `{edit_data['version']}`")

        edit_description = st.text_area("描述", value=edit_data['description'], key="edit_desc")
        edit_pre_process = st.text_input(
            "前处理管道",
            value=edit_data.get('pre_process', ''),
            key="edit_pre_process",
            help="使用管道符分隔，如: fix_orientation|deskew|scale(1024)"
        )
        edit_is_active = st.checkbox("是否激活", value=edit_data['is_active'], key="edit_active")
        edit_weight = st.number_input("权重 (0-100)", min_value=0, max_value=100, value=edit_data['weight'], key="edit_weight")

        col1, col2 = st.columns(2)
        with col1:
            if st.button("💾 保存修改", type="primary"):
                success, msg = update_template(
                    template_id=edit_data['template_id'],
                    version=edit_data['version'],
                    description=edit_description,
                    pre_process=edit_pre_process,
                    is_active=edit_is_active,
                    weight=edit_weight
                )
                if success:
                    st.success(msg)
                    del st.session_state['edit_template']
                    st.rerun()
                else:
                    st.error(msg)
        with col2:
            if st.button("❌ 取消"):
                del st.session_state['edit_template']
                st.rerun()

    st.divider()

    # 新增模板
    st.subheader("➕ 新增模板")

    col1, col2 = st.columns(2)
    with col1:
        new_template_id = st.text_input("模板编号", placeholder="如: invoice_extraction")
        new_template_version = st.text_input("模板版本", value="v1.0.0")
        new_template_doc_type = st.text_input("文档类型", placeholder="如: invoice")
        new_template_pre_process = st.text_input(
            "前处理管道",
            value="",
            placeholder="如: fix_orientation|deskew|scale(1024)",
            help="使用管道符分隔多个处理步骤"
        )
    with col2:
        new_template_description = st.text_area("模板说明", height=100)
        new_template_is_active = st.checkbox("是否激活", value=True)
        new_template_weight = st.number_input("权重 (0-100)", min_value=0, max_value=100, value=100)
        new_template_created_by = st.text_input("创建者", value="streamlit")

    # 配置选择
    st.markdown("**选择配置版本:**")
    col1, col2, col3 = st.columns(3)

    fields_options = get_config_version_options('fields')
    profile_options = get_config_version_options('profile')
    aggregation_options = get_config_version_options('aggregation')

    with col1:
        fields_id = st.selectbox(
            "Fields 配置",
            options=[o['id'] for o in fields_options],
            format_func=lambda x: next((o['label'] for o in fields_options if o['id'] == x), str(x))
        )
    with col2:
        profile_id = st.selectbox(
            "Profile 配置",
            options=[o['id'] for o in profile_options],
            format_func=lambda x: next((o['label'] for o in profile_options if o['id'] == x), str(x))
        )
    with col3:
        aggregation_id = st.selectbox(
            "Aggregation 配置",
            options=[o['id'] for o in aggregation_options],
            format_func=lambda x: next((o['label'] for o in aggregation_options if o['id'] == x), str(x))
        )

    if st.button("💾 保存模板", type="primary"):
        if not new_template_id.strip():
            st.error("模板编号不能为空")
        elif not new_template_doc_type.strip():
            st.error("文档类型不能为空")
        else:
            success, msg = save_template(
                template_id=new_template_id.strip(),
                version=new_template_version.strip() or "v1.0.0",
                doc_type=new_template_doc_type.strip(),
                description=new_template_description,
                fields_config_id=fields_id,
                profile_config_id=profile_id,
                aggregation_config_id=aggregation_id,
                pre_process=new_template_pre_process.strip(),
                is_active=new_template_is_active,
                weight=new_template_weight,
                created_by=new_template_created_by.strip() or "streamlit"
            )
            if success:
                st.success(msg)
                st.rerun()
            else:
                st.error(msg)


def main() -> None:
    """
    Streamlit 应用主入口。
    """
    # 页面配置
    st.set_page_config(
        page_title="Philsee 配置管理 v2.0",
        page_icon="📝",
        layout="wide"
    )

    st.title("📝 配置管理工具 v2.0")
    st.markdown("通用文档解析系统 - 配置模板化管理界面")

    st.divider()

    # 选项卡
    tab1, tab2 = st.tabs(["📋 配置版本管理", "🔧 模板管理"])

    with tab1:
        render_config_versions_tab()

    with tab2:
        render_templates_tab()


if __name__ == "__main__":
    main()
