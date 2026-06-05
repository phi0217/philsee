-- Philsee 数据库初始化脚本（配置模板化 + 分流决策追踪）
-- 版本：v2.0.0
-- 说明：删除旧表并重建，所有旧数据丢失

-- 创建数据库（如果不存在）
CREATE DATABASE IF NOT EXISTS philsee DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE philsee;

-- ============================================================
-- 删除旧表（顺序重要，先删有外键依赖的）
-- ============================================================
DROP TABLE IF EXISTS agg_decisions;
DROP TABLE IF EXISTS field_extractions;
DROP TABLE IF EXISTS requests;
DROP TABLE IF EXISTS config_templates;
DROP TABLE IF EXISTS config_versions;

-- ============================================================
-- 1. 配置版本表（移除 is_active 字段）
-- 所有配置版本均为历史记录，只有被模板引用的版本才会被使用
-- ============================================================
CREATE TABLE config_versions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    version_tag VARCHAR(64) NOT NULL COMMENT '版本标识，如 v1.0.0',
    doc_type VARCHAR(64) NOT NULL COMMENT 'fields 时固定为 *；profile/aggregation 时为具体文档类型',
    config_type ENUM('fields','profile','aggregation') NOT NULL COMMENT '配置类型',
    content JSON NOT NULL COMMENT '配置内容（JSON 格式）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    created_by VARCHAR(64) COMMENT '创建人',
    is_deleted BOOLEAN DEFAULT FALSE COMMENT '是否删除',
    UNIQUE KEY uk_unique (doc_type, config_type, version_tag),
    INDEX idx_doc_type (doc_type),
    INDEX idx_config_type (config_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='配置版本表';

-- ============================================================
-- 2. 配置模板表（新增）
-- 管理配置组合，支持按权重分流
-- ============================================================
CREATE TABLE config_templates (
    id INT PRIMARY KEY AUTO_INCREMENT,
    template_id VARCHAR(64) NOT NULL COMMENT '模板编号，如 invoice_extraction',
    version VARCHAR(32) NOT NULL COMMENT '模板版本，如 v1.0.0',
    doc_type VARCHAR(64) NOT NULL COMMENT '适用的文档类型，如 invoice',
    description TEXT COMMENT '模板说明',
    fields_config_id INT NOT NULL COMMENT '关联 config_versions.id (config_type=fields)',
    profile_config_id INT NOT NULL COMMENT '关联 config_versions.id (config_type=profile)',
    aggregation_config_id INT NOT NULL COMMENT '关联 config_versions.id (config_type=aggregation)',
    pre_process VARCHAR(255) DEFAULT '' COMMENT '前处理管道，管道符分隔，如 "fix_orientation|deskew|scale(1024)"',
    is_active BOOLEAN DEFAULT TRUE COMMENT '是否启用',
    weight INT NOT NULL DEFAULT 0 COMMENT '分流权重（0-100），同一 template_id 下所有 is_active=1 的版本权重和应为 100',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    created_by VARCHAR(64) COMMENT '创建人',
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP COMMENT '更新时间',
    updated_by VARCHAR(64) COMMENT '更新人',
    UNIQUE KEY uk_template_version (template_id, version),
    KEY idx_doc_type (doc_type),
    KEY idx_active (template_id, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='配置模板表';

-- ============================================================
-- 3. 请求主表（增加字段）
-- 新增 template_id、template_version、selected_weight、trace 字段
-- ============================================================
CREATE TABLE requests (
    trace_id VARCHAR(64) PRIMARY KEY COMMENT '请求唯一标识（UUID）',
    doc_type VARCHAR(64) NOT NULL COMMENT '单据类型',
    total_pages INT COMMENT '总页数',
    final_fields JSON COMMENT '最终聚合后的字段结果',
    warnings JSON COMMENT '警告信息列表',
    template_id VARCHAR(64) COMMENT '实际使用的模板编号',
    template_version VARCHAR(32) COMMENT '实际使用的模板版本',
    selected_weight INT COMMENT '命中模板版本的权重',
    trace JSON COMMENT '分流决策详细记录',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    INDEX idx_doc_type (doc_type),
    INDEX idx_template_id (template_id),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='请求主记录表';

-- ============================================================
-- 4. 字段提取详情表（无外键约束）
-- ============================================================
CREATE TABLE field_extractions (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    trace_id VARCHAR(64) NOT NULL COMMENT '关联请求 ID',
    page_num INT NOT NULL COMMENT '页码（从1开始）',
    field_name VARCHAR(64) NOT NULL COMMENT '字段名称',
    extracted_value TEXT COMMENT '提取的值（字符串或 JSON）',
    confidence FLOAT COMMENT '置信度（0~1）',
    raw_response TEXT COMMENT 'VLM 原始响应',
    minio_path VARCHAR(255) COMMENT 'MinIO 图片路径',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    INDEX idx_trace_page (trace_id, page_num),
    INDEX idx_field_name (field_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='字段提取详情表';

-- ============================================================
-- 5. 聚合决策表（无外键约束）
-- ============================================================
CREATE TABLE agg_decisions (
    trace_id VARCHAR(64) NOT NULL COMMENT '关联请求 ID',
    field_name VARCHAR(64) NOT NULL COMMENT '字段名称',
    selected_page INT COMMENT '选中的页码',
    selected_value TEXT COMMENT '最终选中的值',
    reason VARCHAR(255) COMMENT '聚合原因说明',
    candidates JSON COMMENT '所有候选值列表',
    PRIMARY KEY (trace_id, field_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='聚合决策表';

-- ============================================================
-- 插入示例配置数据
-- ============================================================

-- 1. 全局字段定义 (id=1)
INSERT INTO config_versions (id, version_tag, doc_type, config_type, content, created_by)
VALUES (1, 'v1.0.0', '*', 'fields', '{
    "fields": {
        "amount": {"type": "number", "description": "金额"},
        "currency": {"type": "string", "description": "币种"},
        "date": {"type": "string", "description": "日期"},
        "party": {"type": "string", "description": "当事人"},
        "lc_number": {"type": "string", "description": "信用证编号"},
        "commodities": {"type": "list", "description": "商品列表"}
    }
}', 'system');

-- 2. letter_of_credit 的字段策略配置 (id=2)
INSERT INTO config_versions (id, version_tag, doc_type, config_type, content, created_by)
VALUES (2, 'v1.0.0', 'letter_of_credit', 'profile', '{
    "fields": {
        "lc_number": {
            "prompt_hint": "请提取信用证编号，通常以 LC 开头",
            "pages": "first"
        },
        "amount": {
            "prompt_hint": "请提取金额数值",
            "pages": "all"
        },
        "currency": {
            "prompt_hint": "请提取币种代码，如 USD、CNY",
            "pages": "first"
        },
        "date": {
            "prompt_hint": "请提取日期，格式为 YYYY-MM-DD",
            "pages": "first"
        },
        "party": {
            "prompt_hint": "请提取申请人或受益人名称",
            "pages": "all"
        },
        "commodities": {
            "prompt_hint": "请提取商品列表，返回 JSON 数组格式",
            "pages": "all"
        }
    }
}', 'system');

-- 3. letter_of_credit 的聚合规则 (id=3)
INSERT INTO config_versions (id, version_tag, doc_type, config_type, content, created_by)
VALUES (3, 'v1.0.0', 'letter_of_credit', 'aggregation', '{
    "default": {"strategy": "first_non_null"},
    "amount": {"strategy": "max_confidence"},
    "party": {"strategy": "last_non_null"},
    "commodities": {"strategy": "merge_lists"}
}', 'system');

-- 4. 全局聚合规则（备用）(id=4)
INSERT INTO config_versions (id, version_tag, doc_type, config_type, content, created_by)
VALUES (4, 'v1.0.0', '*', 'aggregation', '{
    "default": {"strategy": "first_non_null"},
    "amount": {"strategy": "max_confidence"},
    "commodities": {"strategy": "merge_lists"}
}', 'system');

-- 5. invoice 的字段策略配置 (id=5)
INSERT INTO config_versions (id, version_tag, doc_type, config_type, content, created_by)
VALUES (5, 'v1.0.0', 'invoice', 'profile', '{
    "fields": {
        "amount": {
            "prompt_hint": "请提取发票金额",
            "pages": "all"
        },
        "currency": {
            "prompt_hint": "请提取币种",
            "pages": "first"
        },
        "date": {
            "prompt_hint": "请提取开票日期",
            "pages": "first"
        },
        "party": {
            "prompt_hint": "请提取开票方或收票方名称",
            "pages": "first"
        }
    }
}', 'system');

-- 6. invoice 的聚合规则 (id=6)
INSERT INTO config_versions (id, version_tag, doc_type, config_type, content, created_by)
VALUES (6, 'v1.0.0', 'invoice', 'aggregation', '{
    "default": {"strategy": "first_non_null"},
    "amount": {"strategy": "max_confidence"}
}', 'system');

-- ============================================================
-- 插入示例模板数据
-- ============================================================

-- 1. letter_of_credit 默认模板（100% 权重）
INSERT INTO config_templates (template_id, version, doc_type, description, fields_config_id, profile_config_id, aggregation_config_id, pre_process, is_active, weight, created_by)
VALUES ('lc_extraction', 'v1.0.0', 'letter_of_credit', '信用证解析默认模板', 1, 2, 3, 'fix_orientation|deskew|scale(1024)', TRUE, 100, 'system');

-- 2. invoice 默认模板（100% 权重）
INSERT INTO config_templates (template_id, version, doc_type, description, fields_config_id, profile_config_id, aggregation_config_id, pre_process, is_active, weight, created_by)
VALUES ('invoice_extraction', 'v1.0.0', 'invoice', '发票解析默认模板', 1, 5, 6, 'fix_orientation|scale(1024)', TRUE, 100, 'system');

-- ============================================================
-- 完成提示
-- ============================================================
SELECT '数据库初始化完成！v2.0.0 - 配置模板化 + 分流决策追踪' AS message;
SELECT COUNT(*) AS config_count FROM config_versions;
SELECT COUNT(*) AS template_count FROM config_templates;
