# 核心业务表设计文档

> **版本**: v1.0.0  
> **最后更新**: 2026-06-05  
> **适用项目**: philsee 通用文档解析系统

---

## 目录

1. [config_templates（配置模板表）](#config_templates配置模板表)
2. [requests（请求主表）](#requests请求主表)
3. [field_extractions（字段提取明细表）](#field_extractions字段提取明细表)
4. [agg_decisions（聚合决策表）](#agg_decisions聚合决策表)
5. [表关系总览](#表关系总览)

---

## config_templates（配置模板表）

**存储配置组合（fields + profile + aggregation）的模板，支持多版本按权重分流。**

### 字段详情

| 字段名 | 类型 | 约束 | 可空 | 说明 |
|--------|------|------|------|------|
| `id` | INT | PRIMARY KEY, AUTO_INCREMENT | 否 | 自增主键 |
| `template_id` | VARCHAR(64) | - | 否 | 模板编号，如 `invoice_extraction` |
| `version` | VARCHAR(32) | - | 否 | 版本标识，如 `v1.0.0` |
| `doc_type` | VARCHAR(64) | - | 否 | 文档类型，如 `invoice`、`letter_of_credit` |
| `description` | VARCHAR(255) | - | 是 | 模板描述说明 |
| `fields_config_id` | INT | - | 否 | 引用 config_versions.id（fields 类型配置） |
| `profile_config_id` | INT | - | 否 | 引用 config_versions.id（profile 类型配置） |
| `aggregation_config_id` | INT | - | 否 | 引用 config_versions.id（aggregation 类型配置） |
| `pre_process` | VARCHAR(255) | DEFAULT '' | 是 | 前处理管道，管道符分隔，如 `fix_orientation\|deskew\|scale(1024)` |
| `is_active` | BOOLEAN | DEFAULT TRUE | 否 | 是否激活，激活的版本参与分流 |
| `weight` | INT | DEFAULT 0 | 否 | 分流权重（0-100），同一 template_id 下激活版本权重和应为 100 |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 是 | 创建时间 |
| `created_by` | VARCHAR(64) | - | 是 | 创建人 |
| `updated_at` | TIMESTAMP | - | 是 | 最后更新时间 |
| `updated_by` | VARCHAR(64) | - | 是 | 最后更新人 |

### 索引说明

| 索引名 | 类型 | 字段 | 用途 |
|--------|------|------|------|
| `PRIMARY` | 主键 | `id` | 唯一标识每条记录 |
| `uk_template_version` | 唯一索引 | `(template_id, version)` | 保证同一模板下版本号唯一 |
| `idx_doc_type` | 普通索引 | `doc_type` | 按文档类型快速查找模板 |
| `idx_active` | 普通索引 | `(template_id, is_active)` | 快速查找激活的模板版本用于分流 |

### 表之间的关系

```
config_templates
    ├── fields_config_id → config_versions.id (config_type='fields')
    ├── profile_config_id → config_versions.id (config_type='profile')
    └── aggregation_config_id → config_versions.id (config_type='aggregation')

requests
    └── template_id, template_version → config_templates (记录使用的模板)
```

> **注意**：`fields_config_id`、`profile_config_id`、`aggregation_config_id` 引用 `config_versions.id`，但无外键约束，由应用层保证完整性。

### 示例记录

```sql
INSERT INTO config_templates (
    id, template_id, version, doc_type, description,
    fields_config_id, profile_config_id, aggregation_config_id,
    pre_process, is_active, weight,
    created_at, created_by
) VALUES (
    1, 'invoice_extraction', 'v1.0.0', 'invoice', '发票解析默认模板',
    1, 5, 6,
    'fix_orientation|deskew|scale(1024)',
    TRUE, 100,
    '2026-06-05 10:00:00', 'system'
);
```

**多版本分流示例**：

```sql
-- 同一 template_id 下两个激活版本，权重分别为 70 和 30
INSERT INTO config_templates (template_id, version, doc_type, ..., is_active, weight) VALUES
('invoice_extraction', 'v1.0.0', 'invoice', ..., TRUE, 70),
('invoice_extraction', 'v1.1.0', 'invoice', ..., TRUE, 30);
```

### 注意事项

1. **权重校验**：同一 `template_id` 下所有激活版本（`is_active=TRUE`）的权重和应为 100，但数据库层不强制，由应用层校验。

2. **pre_process 语法**：
   - 使用管道符 `|` 分隔多个处理步骤
   - 步骤按从左到右顺序依次执行
   - 支持的函数：`fix_orientation`、`deskew`、`denoise`、`scale(short_edge)`、`crop(x1,y1,x2,y2)`、`to_grayscale`、`enhance_contrast`
   - 示例：`fix_orientation|deskew|scale(1024)`

3. **配置引用**：三个 `*_config_id` 字段引用的 `config_versions` 记录应分别对应 `config_type` 为 `fields`、`profile`、`aggregation`。

4. **分流逻辑**：请求时系统根据 `template_id` 查找所有激活版本，按权重随机选择一个版本执行。

---

## requests（请求主表）

**记录每次解析请求的总体信息，包括最终提取结果、使用的模板、分流决策痕迹。**

### 字段详情

| 字段名 | 类型 | 约束 | 可空 | 说明 |
|--------|------|------|------|------|
| `trace_id` | VARCHAR(64) | PRIMARY KEY | 否 | 请求唯一标识，UUID 格式 |
| `doc_type` | VARCHAR(64) | - | 否 | 文档类型，如 `invoice` |
| `total_pages` | INT | - | 否 | 文档总页数 |
| `final_fields` | JSON | - | 否 | 聚合后的最终字段值，JSON 格式 |
| `warnings` | JSON | - | 否 | 处理过程中的警告列表，JSON 数组 |
| `template_id` | VARCHAR(64) | - | 是 | 使用的模板编号 |
| `template_version` | VARCHAR(32) | - | 是 | 使用的模板版本 |
| `selected_weight` | INT | - | 是 | 命中模板版本的权重值 |
| `trace` | JSON | - | 是 | 分流决策详情，JSON 格式 |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 否 | 请求创建时间 |

### 索引说明

| 索引名 | 类型 | 字段 | 用途 |
|--------|------|------|------|
| `PRIMARY` | 主键 | `trace_id` | 唯一标识每次请求 |
| `idx_created_at` | 普通索引 | `created_at` | 按时间范围查询请求记录（可选） |

### 表之间的关系

```
requests (trace_id)
    ├── → field_extractions (trace_id)    -- 一对多：一个请求对应多条提取记录
    ├── → agg_decisions (trace_id)        -- 一对多：一个请求对应多条聚合决策
    └── → config_templates (template_id)  -- 逻辑关联：记录使用的模板
```

### 示例记录

```sql
INSERT INTO requests (
    trace_id, doc_type, total_pages,
    final_fields, warnings,
    template_id, template_version, selected_weight, trace,
    created_at
) VALUES (
    '550e8400-e29b-41d4-a716-446655440000',
    'invoice',
    3,
    '{"amount": 12500.00, "currency": "USD", "date": "2026-06-01", "lc_number": "LC123456"}',
    '[]',
    'invoice_extraction',
    'v1.0.0',
    70,
    '{"candidates": [{"version": "v1.0.0", "weight": 70}, {"version": "v1.1.0", "weight": 30}], "random_value": 0.65, "selected_index": 0, "decision": "v1.0.0", "fallback_used": false}',
    '2026-06-05 10:30:00'
);
```

**trace 字段 JSON 结构详解**：

```json
{
  "candidates": [
    {"version": "v1.0.0", "weight": 70},
    {"version": "v1.1.0", "weight": 30}
  ],
  "random_value": 0.65,
  "selected_index": 0,
  "decision": "v1.0.0",
  "fallback_used": false
}
```

| 字段 | 说明 |
|------|------|
| `candidates` | 候选模板版本列表，包含版本号和权重 |
| `random_value` | 随机生成的值（0-1），用于加权随机选择 |
| `selected_index` | 选中的候选索引 |
| `decision` | 最终选择的版本号 |
| `fallback_used` | 是否使用了回退模板 |

**final_fields 字段格式**：

```json
{
  "amount": 12500.00,
  "currency": "USD",
  "date": "2026-06-01",
  "lc_number": "LC123456",
  "party": "ABC Company Ltd.",
  "commodities": [
    {"hs_code": "8471.30", "quantity": 100, "unit_price": 50.00}
  ]
}
```

### 注意事项

1. **trace_id 生成**：由应用层生成 UUID，保证全局唯一。

2. **final_fields 格式**：与 `config_versions` 中 `fields` 配置的字段定义对应，键为字段名，值为提取结果。

3. **warnings 结构**：JSON 数组，每个元素包含 `level`、`message`、`field` 等信息：

```json
[
  {"level": "warning", "message": "字段 amount 置信度较低", "field": "amount"},
  {"level": "info", "message": "第2页识别跳过", "field": null}
]
```

4. **trace 用途**：用于调试分流逻辑和 A/B 测试分析，记录完整的决策过程。

5. **事务一致性**：`requests`、`field_extractions`、`agg_decisions` 三张表的写入在同一事务中完成，保证数据一致性。

---

## field_extractions（字段提取明细表）

**记录每页每个字段的原始提取结果，用于调试、复审和自优化。**

### 字段详情

| 字段名 | 类型 | 约束 | 可空 | 说明 |
|--------|------|------|------|------|
| `id` | INT | PRIMARY KEY, AUTO_INCREMENT | 否 | 自增主键 |
| `trace_id` | VARCHAR(64) | - | 否 | 关联 requests.trace_id |
| `page_num` | INT | - | 否 | 页码（从 1 开始） |
| `field_name` | VARCHAR(64) | - | 否 | 字段名称 |
| `extracted_value` | TEXT | - | 是 | 经过类型转换后的提取值 |
| `confidence` | FLOAT | - | 否 | VLM 返回的置信度（0-1） |
| `raw_response` | TEXT | - | 是 | VLM 返回的原始文本，未解析 |
| `minio_path` | VARCHAR(255) | - | 是 | 该页图片在 MinIO 中的存储路径 |
| `created_at` | TIMESTAMP | DEFAULT CURRENT_TIMESTAMP | 否 | 记录创建时间 |

### 索引说明

| 索引名 | 类型 | 字段 | 用途 |
|--------|------|------|------|
| `PRIMARY` | 主键 | `id` | 唯一标识每条记录 |
| `idx_trace_page` | 普通索引 | `(trace_id, page_num)` | 按请求和页码查询提取结果 |

### 表之间的关系

```
field_extractions
    └── trace_id → requests.trace_id (逻辑关联，无外键)
```

### 示例记录

```sql
INSERT INTO field_extractions (
    id, trace_id, page_num, field_name,
    extracted_value, confidence, raw_response, minio_path,
    created_at
) VALUES (
    1, '550e8400-e29b-41d4-a716-446655440000', 1, 'amount',
    '12500.00', 0.95, '12500.00 USD', 'documents/2026/06/550e8400/page_001.jpg',
    '2026-06-05 10:30:05'
);
```

**多字段多页示例**：

```sql
-- 同一请求的多页多字段提取记录
INSERT INTO field_extractions (trace_id, page_num, field_name, extracted_value, confidence, raw_response, minio_path) VALUES
('550e8400-...', 1, 'lc_number', 'LC123456', 0.98, 'LC123456', 'documents/.../page_001.jpg'),
('550e8400-...', 1, 'amount', '12500.00', 0.95, '12500.00 USD', 'documents/.../page_001.jpg'),
('550e8400-...', 2, 'amount', '12500.00', 0.92, 'Total: 12500.00', 'documents/.../page_002.jpg'),
('550e8400-...', 3, 'party', 'ABC Company Ltd.', 0.88, 'ABC Company Ltd.', 'documents/.../page_003.jpg');
```

### 注意事项

1. **raw_response 重要性**：存储 VLM 返回的原始文本，是分析提取错误的关键数据。当 `extracted_value` 解析失败时，可通过 `raw_response` 排查问题。

2. **extracted_value 格式**：
   - 简单类型（string/number）：直接存储字符串形式
   - 复杂类型（list/object）：存储 JSON 字符串

```sql
-- 列表字段示例
extracted_value: '[{"hs_code": "8471.30", "quantity": 100}]'

-- 对象字段示例
extracted_value: '{"country": "CN", "city": "Shanghai"}'
```

3. **minio_path 格式**：`{bucket}/{year}/{month}/{trace_id}/page_{num}.jpg`

4. **置信度范围**：0-1 的浮点数，越高表示 VLM 对提取结果越确信。

5. **批量写入**：一个请求的所有提取记录批量写入，减少数据库交互次数。

---

## agg_decisions（聚合决策表）

**记录每个字段的跨页聚合决策过程，用于审计和调试聚合逻辑。**

### 字段详情

| 字段名 | 类型 | 约束 | 可空 | 说明 |
|--------|------|------|------|------|
| `trace_id` | VARCHAR(64) | PRIMARY KEY (复合) | 否 | 关联 requests.trace_id |
| `field_name` | VARCHAR(64) | PRIMARY KEY (复合) | 否 | 字段名称 |
| `selected_page` | INT | - | 是 | 最终选择的页码，全为 null 时为 NULL |
| `selected_value` | TEXT | - | 是 | 最终选择的值 |
| `reason` | VARCHAR(64) | - | 否 | 聚合决策原因 |
| `candidates` | JSON | - | 否 | 候选值列表，JSON 数组格式 |

### 索引说明

| 索引名 | 类型 | 字段 | 用途 |
|--------|------|------|------|
| `PRIMARY` | 复合主键 | `(trace_id, field_name)` | 唯一标识每个请求的每个字段决策 |

### 表之间的关系

```
agg_decisions
    └── trace_id → requests.trace_id (逻辑关联，无外键)
```

### 示例记录

```sql
INSERT INTO agg_decisions (
    trace_id, field_name, selected_page, selected_value, reason, candidates
) VALUES (
    '550e8400-e29b-41d4-a716-446655440000',
    'amount',
    2,
    '12500.00',
    'max_confidence',
    '[{"page": 1, "value": "12500.00", "confidence": 0.85}, {"page": 2, "value": "12500.00", "confidence": 0.95}]'
);
```

**reason 常见取值**：

| 值 | 说明 | 场景 |
|----|------|------|
| `first_non_null` | 按页码顺序取第一个非空值 | 字段首次出现在文档中间 |
| `last_non_null` | 按页码顺序取最后一个非空值 | 字段最后出现在文档末尾 |
| `max_confidence` | 取置信度最高的值 | 关键字段需要高准确性 |
| `merge_lists` | 按页码顺序合并所有列表 | 多页分布的列表数据 |
| `first_non_null_all_none` | 所有值都为空 | 无有效提取结果 |

**candidates JSON 结构**：

```json
[
  {"page": 1, "value": "12500.00", "confidence": 0.85},
  {"page": 2, "value": "12500.00", "confidence": 0.95},
  {"page": 3, "value": null, "confidence": 0.0}
]
```

**merge_lists 策略示例**：

```sql
INSERT INTO agg_decisions (
    trace_id, field_name, selected_page, selected_value, reason, candidates
) VALUES (
    '550e8400-...',
    'commodities',
    NULL,
    '[{"hs_code": "8471.30", "quantity": 100}, {"hs_code": "8471.41", "quantity": 50}]',
    'merge_lists',
    '[{"page": 1, "value": [{"hs_code": "8471.30", "quantity": 100}], "confidence": 0.90}, {"page": 2, "value": [{"hs_code": "8471.41", "quantity": 50}], "confidence": 0.88}]'
);
```

### 注意事项

1. **复合主键**：`(trace_id, field_name)` 保证每个请求的每个字段只有一条决策记录。

2. **selected_page 为 NULL 的场景**：
   - 使用 `merge_lists` 策略时，结果来自多页合并
   - 所有候选值都为空时（`first_non_null_all_none`）

3. **selected_value 与 final_fields 对应**：`agg_decisions.selected_value` 应与 `requests.final_fields` 中对应字段的值一致。

4. **审计用途**：通过 `candidates` 可追溯聚合决策的全过程，便于分析：
   - 为什么选择了某个值
   - 哪些页有提取结果
   - 各页置信度对比

5. **调试建议**：当聚合结果不符合预期时，首先查看 `agg_decisions` 表的 `reason` 和 `candidates` 字段。

---

## 表关系总览

```
                              ┌─────────────────────┐
                              │   config_versions   │
                              │  (配置版本表)        │
                              └─────────────────────┘
                                        ▲
                     ┌──────────────────┼──────────────────┐
                     │ fields_config_id │ profile_config_id│ aggregation_config_id
                     │                  │                  │
┌─────────────────────┴──────────────────┴──────────────────┴─────────────────────┐
│                              config_templates                                    │
│                              (配置模板表)                                         │
│  - 组合 fields + profile + aggregation 配置                                      │
│  - 支持多版本权重分流                                                             │
│  - 定义 pre_process 前处理管道                                                    │
└──────────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        │ template_id, template_version
                                        ▼
┌──────────────────────────────────────────────────────────────────────────────────┐
│                                   requests                                       │
│                                (请求主表)                                         │
│  - 记录每次解析请求                                                               │
│  - 存储最终结果 final_fields                                                      │
│  - 记录分流决策 trace                                                            │
└──────────────────────────────────────────────────────────────────────────────────┘
                          │                                    │
                          │ trace_id                          │ trace_id
                          ▼                                    ▼
┌──────────────────────────────────────┐    ┌──────────────────────────────────────┐
│        field_extractions             │    │          agg_decisions               │
│        (字段提取明细表)               │    │          (聚合决策表)                 │
│  - 每页每个字段的提取结果             │    │  - 每个字段的聚合决策过程              │
│  - 存储 raw_response 原始响应        │    │  - 记录 candidates 候选列表           │
│  - 记录 confidence 置信度            │    │  - 记录 reason 决策原因               │
└──────────────────────────────────────┘    └──────────────────────────────────────┘
```

### 数据流向

```
1. 请求进入
   ↓
2. 根据 template_id 查找激活的 config_templates 版本
   ↓
3. 按权重随机选择一个版本
   ↓
4. 加载对应的 fields/profile/aggregation 配置
   ↓
5. 执行 pre_process 前处理管道
   ↓
6. 逐页调用 VLM 提取字段 → 写入 field_extractions
   ↓
7. 执行聚合策略 → 写入 agg_decisions
   ↓
8. 生成最终结果 → 写入 requests
```

---

## 附录

### 相关文件

| 文件 | 说明 |
|------|------|
| [sql/init_db.sql](../../sql/init_db.sql) | 数据库初始化脚本 |
| [online/config_loader.py](../../online/config_loader.py) | 配置加载模块，包含 ConfigTemplate 模型 |
| [online/db_writer.py](../../online/db_writer.py) | 数据库写入模块 |
| [online/aggregator.py](../../online/aggregator.py) | 聚合处理模块 |
| [develop/doc/config_versions_content_spec.md](./config_versions_content_spec.md) | config_versions 表 content 字段规范 |

### 版本历史

| 版本 | 日期 | 变更说明 |
|------|------|----------|
| v1.0.0 | 2026-06-05 | 初始版本，包含四张核心业务表设计文档 |

---

> 📝 **文档维护**: 如有问题或建议，请联系项目维护人员。
