"""
Streamlit 配置管理工具 - 通用文档解析系统 (philsee)

该模块提供对 MySQL 数据库中 config_versions 表的管理界面，
支持配置的查看、编辑、版本管理（增、改、激活历史版本）。
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


def get_existing_doc_types() -> list[str]:
    """
    从数据库获取已存在的文档类型列表。

    Returns:
        list[str]: 文档类型列表，按字母排序。
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = """
                SELECT DISTINCT doc_type
                FROM config_versions
                WHERE is_deleted = 0
                ORDER BY doc_type
            """
            cursor.execute(sql)
            results = cursor.fetchall()
            return [row['doc_type'] for row in results]
    except pymysql.Error as e:
        logger.error(f"获取文档类型列表失败: {e}")
        return []
    finally:
        conn.close()


def get_active_config(doc_type: str, config_type: str) -> Optional[dict[str, Any]]:
    """
    获取指定文档类型和配置类型的激活配置。

    Args:
        doc_type: 文档类型标识。
        config_type: 配置类型 (fields/profile/aggregation)。

    Returns:
        Optional[dict]: 激活的配置记录，包含 id、version_tag、content 等字段，
                        如果不存在则返回 None。
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = """
                SELECT id, version_tag, content, created_at, created_by
                FROM config_versions
                WHERE doc_type = %s
                  AND config_type = %s
                  AND is_active = 1
                  AND is_deleted = 0
                LIMIT 1
            """
            cursor.execute(sql, (doc_type, config_type))
            result = cursor.fetchone()
            return result
    except pymysql.Error as e:
        logger.error(f"获取激活配置失败: {e}")
        return None
    finally:
        conn.close()


def get_all_versions(doc_type: str, config_type: str) -> list[dict[str, Any]]:
    """
    获取指定文档类型和配置类型的所有历史版本。

    Args:
        doc_type: 文档类型标识。
        config_type: 配置类型 (fields/profile/aggregation)。

    Returns:
        list[dict]: 版本列表，按 id 降序排列。
    """
    try:
        conn = get_db_connection()
        with conn.cursor() as cursor:
            sql = """
                SELECT id, version_tag, content, created_at, created_by, is_active
                FROM config_versions
                WHERE doc_type = %s
                  AND config_type = %s
                  AND is_deleted = 0
                ORDER BY id DESC
            """
            cursor.execute(sql, (doc_type, config_type))
            return cursor.fetchall()
    except pymysql.Error as e:
        logger.error(f"获取历史版本失败: {e}")
        return []
    finally:
        conn.close()


def validate_config_content(content: dict, config_type: str) -> tuple[bool, list[str]]:
    """
    校验配置内容的格式合法性。

    执行通用格式校验，不针对特定业务逻辑。

    Args:
        content: 解析后的 JSON 配置内容。
        config_type: 配置类型 (fields/profile/aggregation)。

    Returns:
        tuple[bool, list[str]]: (是否通过校验, 警告消息列表)。
    """
    warnings = []

    if config_type == 'fields':
        # fields 类型建议包含顶层 "fields" 键
        if 'fields' not in content:
            warnings.append("建议: fields 类型配置应包含顶层 'fields' 键")
        elif not isinstance(content.get('fields'), dict):
            warnings.append("建议: 'fields' 键的值应为对象类型")

    elif config_type == 'profile':
        # profile 类型建议包含 "doc_type" 和 "fields" 键
        if 'doc_type' not in content:
            warnings.append("建议: profile 类型配置应包含 'doc_type' 键")
        if 'fields' not in content:
            warnings.append("建议: profile 类型配置应包含 'fields' 键")

    elif config_type == 'aggregation':
        # aggregation 类型应为非空对象
        if not content:
            warnings.append("建议: aggregation 类型配置不应为空对象")

    # 通过校验（仅有警告，不阻止保存）
    return True, warnings


def save_new_version(
    doc_type: str,
    config_type: str,
    content: dict,
    version_tag: str,
    created_by: str
) -> tuple[bool, str]:
    """
    保存配置为新版本并设为激活状态。

    使用数据库事务确保原子性：
    1. 将同组所有版本的 is_active 设为 0
    2. 插入新版本记录，is_active = 1

    Args:
        doc_type: 文档类型标识。
        config_type: 配置类型。
        content: 配置内容（字典）。
        version_tag: 版本标签。
        created_by: 创建者。

    Returns:
        tuple[bool, str]: (是否成功, 消息)。
    """
    conn = None
    try:
        conn = get_db_connection()
        conn.begin()  # 开启事务

        with conn.cursor() as cursor:
            # 1. 将同组所有版本的 is_active 设为 0
            update_sql = """
                UPDATE config_versions
                SET is_active = 0
                WHERE doc_type = %s AND config_type = %s AND is_deleted = 0
            """
            cursor.execute(update_sql, (doc_type, config_type))

            # 2. 插入新版本记录
            insert_sql = """
                INSERT INTO config_versions
                (version_tag, doc_type, config_type, content, created_at, created_by, is_active, is_deleted)
                VALUES (%s, %s, %s, %s, %s, %s, 1, 0)
            """
            cursor.execute(insert_sql, (
                version_tag,
                doc_type,
                config_type,
                json.dumps(content, ensure_ascii=False),
                datetime.now(),
                created_by
            ))

        conn.commit()  # 提交事务
        logger.info(f"保存新版本成功: {doc_type}/{config_type}@{version_tag}")
        return True, f"版本 {version_tag} 保存成功！"
    except pymysql.Error as e:
        if conn:
            conn.rollback()  # 回滚事务
        logger.error(f"保存新版本失败: {e}")
        return False, f"保存失败: {str(e)}"
    finally:
        if conn:
            conn.close()


def activate_version(version_id: int, doc_type: str, config_type: str) -> tuple[bool, str]:
    """
    激活指定的历史版本。

    使用数据库事务确保原子性：
    1. 将同组所有版本的 is_active 设为 0
    2. 将指定版本的 is_active 设为 1

    Args:
        version_id: 要激活的版本 ID。
        doc_type: 文档类型标识。
        config_type: 配置类型。

    Returns:
        tuple[bool, str]: (是否成功, 消息)。
    """
    conn = None
    try:
        conn = get_db_connection()
        conn.begin()  # 开启事务

        with conn.cursor() as cursor:
            # 1. 将同组所有版本的 is_active 设为 0
            update_all_sql = """
                UPDATE config_versions
                SET is_active = 0
                WHERE doc_type = %s AND config_type = %s AND is_deleted = 0
            """
            cursor.execute(update_all_sql, (doc_type, config_type))

            # 2. 将指定版本的 is_active 设为 1
            update_one_sql = """
                UPDATE config_versions
                SET is_active = 1
                WHERE id = %s
            """
            cursor.execute(update_one_sql, (version_id,))

        conn.commit()  # 提交事务
        logger.info(f"激活版本成功: ID={version_id}")
        return True, "版本激活成功！"
    except pymysql.Error as e:
        if conn:
            conn.rollback()  # 回滚事务
        logger.error(f"激活版本失败: {e}")
        return False, f"激活失败: {str(e)}"
    finally:
        if conn:
            conn.close()


def main() -> None:
    """
    Streamlit 应用主入口。

    构建配置管理界面，包含：
    - 侧边栏选择文档类型和配置类型
    - 展示当前激活配置
    - 编辑并保存新版本
    - 历史版本列表与激活功能
    """
    # 页面配置
    st.set_page_config(
        page_title="Philsee 配置管理",
        page_icon="📝",
        layout="wide"
    )

    st.title("📝 配置管理工具")
    st.markdown("通用文档解析系统 - 配置版本管理界面")

    st.divider()

    # ========== 侧边栏：选择配置 ==========
    st.sidebar.header("配置选择")

    # 获取已有的文档类型
    existing_doc_types = get_existing_doc_types()

    # 文档类型选择：下拉选择或手动输入
    st.sidebar.subheader("文档类型 (doc_type)")

    # 选择模式
    input_mode = st.sidebar.radio(
        "输入方式",
        options=["从已有类型选择", "手动输入新类型"],
        label_visibility="collapsed"
    )

    if input_mode == "从已有类型选择":
        if existing_doc_types:
            doc_type = st.sidebar.selectbox(
                "选择文档类型",
                options=existing_doc_types,
                label_visibility="collapsed"
            )
        else:
            st.sidebar.info("暂无已有文档类型，请手动输入")
            doc_type = st.sidebar.text_input(
                "输入文档类型",
                value="*",
                placeholder="例如: invoice, contract, *",
                label_visibility="collapsed"
            )
    else:
        doc_type = st.sidebar.text_input(
            "输入文档类型",
            value="*",
            placeholder="例如: invoice, contract, *",
            label_visibility="collapsed"
        )

    # 配置类型选择
    st.sidebar.subheader("配置类型 (config_type)")
    config_type = st.sidebar.selectbox(
        "选择配置类型",
        options=["fields", "profile", "aggregation"],
        label_visibility="collapsed"
    )

    st.sidebar.divider()
    st.sidebar.markdown(f"**当前选择:** `{doc_type}` / `{config_type}`")

    # ========== 主内容区：展示激活配置 ==========
    st.header("📄 当前激活配置")

    active_config = get_active_config(doc_type, config_type)

    if active_config:
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("版本标签", active_config['version_tag'])
        with col2:
            st.metric("创建者", active_config['created_by'] or "-")
        with col3:
            st.metric("创建时间", active_config['created_at'].strftime("%Y-%m-%d %H:%M:%S") if active_config['created_at'] else "-")

        st.subheader("配置内容 (JSON)")
        st.json(active_config['content'])
    else:
        st.warning(f"⚠️ 当前没有激活的 `{config_type}` 配置用于文档类型 `{doc_type}`")

    st.divider()

    # ========== 编辑并保存新版本 ==========
    st.header("✏️ 编辑并保存为新版本")

    # 预填充当前激活配置的 JSON
    if active_config:
        default_json = json.dumps(active_config['content'], ensure_ascii=False, indent=2)
    else:
        default_json = "{}"

    # JSON 编辑区
    edited_json = st.text_area(
        "配置内容 (JSON 格式)",
        value=default_json,
        height=300,
        key="json_editor"
    )

    # 版本信息输入
    col1, col2 = st.columns(2)
    with col1:
        new_version_tag = st.text_input(
            "版本标签 (version_tag)",
            value="",
            placeholder="例如: v1.0.1"
        )
    with col2:
        new_created_by = st.text_input(
            "创建者 (created_by)",
            value="streamlit"
        )

    # 保存按钮
    if st.button("💾 保存为新版本", type="primary"):
        # 校验版本标签
        if not new_version_tag.strip():
            st.error("❌ 版本标签不能为空！")
        else:
            # 校验 JSON 格式
            try:
                parsed_content = json.loads(edited_json)
            except json.JSONDecodeError as e:
                st.error(f"❌ JSON 格式错误: {e}")
            else:
                # 格式校验（仅警告）
                _, warnings = validate_config_content(parsed_content, config_type)
                for warning in warnings:
                    st.warning(f"⚠️ {warning}")

                # 保存新版本
                success, message = save_new_version(
                    doc_type=doc_type,
                    config_type=config_type,
                    content=parsed_content,
                    version_tag=new_version_tag.strip(),
                    created_by=new_created_by.strip() or "streamlit"
                )

                if success:
                    st.success(f"✅ {message}")
                    st.rerun()  # 刷新页面
                else:
                    st.error(f"❌ {message}")

    st.divider()

    # ========== 历史版本列表 ==========
    st.header("📜 历史版本列表")

    all_versions = get_all_versions(doc_type, config_type)

    if all_versions:
        for version in all_versions:
            with st.container(border=True):
                col1, col2, col3, col4, col5 = st.columns([2, 2, 2, 1, 1])

                with col1:
                    st.markdown(f"**版本:** `{version['version_tag']}`")
                with col2:
                    st.markdown(f"**创建者:** {version['created_by'] or '-'}")
                with col3:
                    created_time = version['created_at'].strftime("%Y-%m-%d %H:%M:%S") if version['created_at'] else "-"
                    st.markdown(f"**时间:** {created_time}")
                with col4:
                    if version['is_active']:
                        st.success("✅ 激活")
                    else:
                        st.info("未激活")
                with col5:
                    if not version['is_active']:
                        # 激活按钮
                        if st.button(
                            "🔄 激活",
                            key=f"activate_{version['id']}",
                            type="secondary"
                        ):
                            success, message = activate_version(
                                version_id=version['id'],
                                doc_type=doc_type,
                                config_type=config_type
                            )
                            if success:
                                st.success(f"✅ {message}")
                                st.rerun()  # 刷新页面
                            else:
                                st.error(f"❌ {message}")

                # 展示配置内容（可折叠）
                with st.expander("查看配置内容"):
                    st.json(version['content'])
    else:
        st.info(f"暂无 `{config_type}` 类型配置的历史版本用于文档类型 `{doc_type}`")


if __name__ == "__main__":
    main()
