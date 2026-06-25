# 配置指南

本文档详细说明 Philsee 的配置模板机制。

## 配置架构

Philsee 采用 **两表设计** 管理配置：

```
┌─────────────────────┐         ┌─────────────────────┐
│   config_versions   │         │  config_templates   │
├─────────────────────┤         ├─────────────────────┤
│ id                  │◄────────│ fields_config_id    │
│ version_tag         │         │ profile_config_id   │
│ doc_type            │         │ aggregation_config_id│
│ config_type         │         │                     │
│ content (JSON)      │         │ template_id         │
└─────────────────────┘         │ version             │
                                │ weight              │
                                │ is_active           │
                                └─────────────────────┘
```

**核心思想**：
- `config_versions` 存储配置的原始版本（不变）
- `config_templates` 组合配置形成可用的模板（可激活/停用）

## 配置类型

### fields 配置

定义全局字段及其类型。`doc_type` 固定为 `*`（全局）。

```json
{
  "fields": {
    "amount": {
      "type": "number",
      "description": "金额"
    },
    "currency": {
      "type": "string",
      "description": "货币代码"
    },
    "date": {
      "type": "date",
      "description": "日期"
    },
    "party_name": {
      "type": "string",
      "description": "当事人名称"
    }
  }
}
```

### profile 配置

定义特定文档类型的字段提取策略。`doc_type` 为具体文档类型。

```json
{
  "doc_type": "letter_of_credit",
  "fields": {
    "amount": {
      "prompt_hint": "信用证金额，通常在金额栏目中",
      "pages": "all",
      "required": true
    },
    "currency": {
      "prompt_hint": "货币代码，如 USD、CNY",
      "pages": "1",
      "required": true
    },
    "date": {
      "prompt_hint": "开证日期",
      "pages": "1",
      "required": false
    }
  }
}
```

**字段说明**：
- `prompt_hint`: 提示词，帮助 VLM 定位字段
- `pages`: 提取页码策略
  - `"all"`: 所有页提取
  - `"1"`: 仅第一页
  - `"1,2"`: 第一页和第二页
  - `"last"`: 最后一页
- `required`: 是否必填

### aggregation 配置

定义跨页聚合策略。`doc_type` 与 profile 一致。

```json
{
  "amount": {
    "strategy": "max_confidence",
    "reason": "金额需要高准确性"
  },
  "currency": {
    "strategy": "first_non_null",
    "reason": "货币通常在第一页确定"
  },
  "date": {
    "strategy": "first_non_null"
  }
}
```

**聚合策略**：

| 策略 | 说明 | 适用场景 |
|------|------|----------|
| `first_non_null` | 取第一个非空值 | 单次出现字段 |
| `last_non_null` | 取最后一个非空值 | 可能更新的字段 |
| `max_confidence` | 取置信度最高的值 | 需要高准确性 |
| `merge_lists` | 合并所有列表 | 多页列表 |

## 模板管理

### 创建模板

**方式一：手动创建**

1. 插入 fields 配置：
```sql
INSERT INTO config_versions (version_tag, doc_type, config_type, content, created_by)
VALUES ('v1.0.0', '*', 'fields', '{"fields": {...}}', 'admin');
-- 获取 fields_config_id
```

2. 插入 profile 配置：
```sql
INSERT INTO config_versions (version_tag, doc_type, config_type, content, created_by)
VALUES ('v1.0.0', 'letter_of_credit', 'profile', '{"doc_type": "...", ...}', 'admin');
-- 获取 profile_config_id
```

3. 插入 aggregation 配置：
```sql
INSERT INTO config_versions (version_tag, doc_type, config_type, content, created_by)
VALUES ('v1.0.0', 'letter_of_credit', 'aggregation', '{"amount": {...}, ...}', 'admin');
-- 获取 aggregation_config_id
```

4. 创建模板：
```sql
INSERT INTO config_templates (
    template_id, version, doc_type, description,
    fields_config_id, profile_config_id, aggregation_config_id,
    is_active, weight, created_by
) VALUES (
    'lc_extraction', 'v1.0.0', 'letter_of_credit', '信用证解析模板',
    1, 2, 3, TRUE, 100, 'admin'
);
```

**方式二：自动生成**

使用 `/generate_template` 接口：
```bash
curl -X POST "http://localhost:8000/generate_template" \
  -F "files=@sample1.jpg" \
  -F "doc_type=letter_of_credit"
```

### 权重分流

同一 `template_id` 下可以有多个激活版本，系统按权重随机选择：

```sql
-- v1.0.0 权重 80%
INSERT INTO config_templates (...) VALUES ('lc_extraction', 'v1.0.0', ..., TRUE, 80);

-- v2.0.0 权重 20%
INSERT INTO config_templates (...) VALUES ('lc_extraction', 'v2.0.0', ..., TRUE, 20);
```

**权重规则**：
- 同一 `template_id` 下所有 `is_active=TRUE` 的权重和应为 100
- 权重和不为 100 时，系统会按比例调整
- 分流决策记录在 `requests.trace` 字段

### doc_type 映射

当请求只提供 `doc_type` 时，系统需要映射到默认 `template_id`：

```yaml
# config/default_templates.yaml (规划中)
default_templates:
  letter_of_credit: "lc_extraction"
  invoice: "invoice_extraction"
  bill_of_lading: "bl_extraction"
```

## 配置版本管理

### 版本标识规则

- `config_versions.version_tag`: 建议使用语义化版本（如 `v1.0.0`）
- `config_templates.version`: 模板版本号，可独立递增

### 版本演进

```sql
-- 创建新版本配置
INSERT INTO config_versions (version_tag, doc_type, config_type, content, created_by)
VALUES ('v1.1.0', 'letter_of_credit', 'profile', '{"doc_type": "...", ...}', 'admin');

-- 创建新版本模板
INSERT INTO config_templates (
    template_id, version, doc_type, description,
    fields_config_id, profile_config_id, aggregation_config_id,
    is_active, weight
) VALUES (
    'lc_extraction', 'v1.1.0', 'letter_of_credit', '信用证解析模板 v1.1',
    1, 4, 3, TRUE, 100
);

-- 停用旧版本
UPDATE config_templates SET is_active = FALSE WHERE template_id = 'lc_extraction' AND version = 'v1.0.0';
```

## Streamlit 配置管理工具

```bash
cd develop/script/streamlit
streamlit run config_ui.py
```

**功能模块**：

1. **配置版本管理**
   - 查看、新增、删除配置版本
   - 支持 fields、profile、aggregation 三种类型

2. **模板管理**
   - 查看所有模板（按 template_id 分组）
   - 新增模板：选择三个配置版本组合
   - 编辑模板：修改权重、激活状态、描述
   - 权重校验：显示同一 template_id 下权重总和

## 最佳实践

1. **配置复用**：fields 配置可以跨 doc_type 共享
2. **渐进发布**：通过权重分流实现 A/B 测试
3. **版本追溯**：保留历史版本配置，便于回滚
4. **决策追踪**：检查 `requests.trace` 字段了解分流决策
