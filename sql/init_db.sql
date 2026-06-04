-- Philsee 数据库初始化脚本
-- 创建所有必要的表结构

-- 创建数据库（如果不存在）
CREATE DATABASE IF NOT EXISTS philsee DEFAULT CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

USE philsee;

-- 1. 配置版本表
-- 存储字段定义、字段策略和聚合规则的版本化配置
CREATE TABLE IF NOT EXISTS config_versions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    version_tag VARCHAR(64) NOT NULL COMMENT '版本标签，如 v1.0.0',
    doc_type VARCHAR(32) NOT NULL COMMENT '单据类型，如 letter_of_credit，* 表示全局',
    config_type ENUM('fields', 'profile', 'aggregation') NOT NULL COMMENT '配置类型',
    content JSON NOT NULL COMMENT '配置内容（JSON 格式）',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    created_by VARCHAR(64) COMMENT '创建人',
    is_active BOOLEAN DEFAULT FALSE COMMENT '是否激活',
    is_deleted BOOLEAN DEFAULT FALSE COMMENT '是否删除',
    INDEX idx_doc_type (doc_type),
    INDEX idx_version_tag (version_tag),
    INDEX idx_active (is_active, is_deleted)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='配置版本表';

-- 2. 请求主记录表
-- 存储每次解析请求的基本信息和最终结果
CREATE TABLE IF NOT EXISTS requests (
    trace_id VARCHAR(64) PRIMARY KEY COMMENT '请求唯一标识（UUID）',
    doc_type VARCHAR(32) NOT NULL COMMENT '单据类型',
    total_pages INT COMMENT '总页数',
    final_fields JSON COMMENT '最终聚合后的字段结果',
    warnings JSON COMMENT '警告信息列表',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP COMMENT '创建时间',
    INDEX idx_doc_type (doc_type),
    INDEX idx_created_at (created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='请求主记录表';

-- 3. 字段提取详情表
-- 存储每页每个字段的提取详情
CREATE TABLE IF NOT EXISTS field_extractions (
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
    INDEX idx_field_name (field_name),
    FOREIGN KEY (trace_id) REFERENCES requests(trace_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='字段提取详情表';

-- 4. 聚合决策表
-- 存储字段聚合的决策过程
CREATE TABLE IF NOT EXISTS agg_decisions (
    trace_id VARCHAR(64) NOT NULL COMMENT '关联请求 ID',
    field_name VARCHAR(64) NOT NULL COMMENT '字段名称',
    selected_page INT COMMENT '选中的页码',
    selected_value TEXT COMMENT '最终选中的值',
    reason VARCHAR(255) COMMENT '聚合原因说明',
    candidates JSON COMMENT '所有候选值列表',
    PRIMARY KEY (trace_id, field_name),
    FOREIGN KEY (trace_id) REFERENCES requests(trace_id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='聚合决策表';

-- ============================================================
-- 插入示例配置数据
-- ============================================================

-- 全局字段定义
INSERT INTO config_versions (version_tag, doc_type, config_type, content, is_active, created_by)
VALUES (
    'v1.0.0',
    '*',
    'fields',
    '{
        "amount": {"type": "number", "description": "金额"},
        "currency": {"type": "string", "description": "币种"},
        "date": {"type": "string", "description": "日期"},
        "party": {"type": "string", "description": "当事人"},
        "lc_number": {"type": "string", "description": "信用证编号"},
        "commodities": {"type": "list", "description": "商品列表"}
    }',
    TRUE,
    'system'
);

-- letter_of_credit 的字段策略配置
INSERT INTO config_versions (version_tag, doc_type, config_type, content, is_active, created_by)
VALUES (
    'v1.0.0',
    'letter_of_credit',
    'profile',
    '{
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
    }',
    TRUE,
    'system'
);

-- 全局聚合规则
INSERT INTO config_versions (version_tag, doc_type, config_type, content, is_active, created_by)
VALUES (
    'v1.0.0',
    '*',
    'aggregation',
    '{
        "default": {"strategy": "first_non_null"},
        "amount": {"strategy": "max_confidence"},
        "commodities": {"strategy": "merge_lists"}
    }',
    TRUE,
    'system'
);

-- letter_of_credit 特定的聚合规则
INSERT INTO config_versions (version_tag, doc_type, config_type, content, is_active, created_by)
VALUES (
    'v1.0.0',
    'letter_of_credit',
    'aggregation',
    '{
        "default": {"strategy": "first_non_null"},
        "amount": {"strategy": "max_confidence"},
        "party": {"strategy": "last_non_null"},
        "commodities": {"strategy": "merge_lists"}
    }',
    TRUE,
    'system'
);

-- ============================================================
-- 完成提示
-- ============================================================
SELECT '数据库初始化完成！' AS message;
SELECT COUNT(*) AS config_count FROM config_versions;
