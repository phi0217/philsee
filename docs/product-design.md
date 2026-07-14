# Philsee 智能单据解析服务 — 分层架构产品设计与功能用法

> 版本：v2.1.0 | 更新时间：2026-07-14
> 技术栈：FastAPI + SQLAlchemy(async) + MySQL + MinIO + VLM

---

## 一、产品概述

### 1.1 核心能力

Philsee 是一个**智能单据解析服务**，核心解决一个问题：

> 用户上传多页单据图片 → 自动识别字段 → 跨页合并 → 结果存入数据库

适用于发票识别、信用证解析、报关单识别等场景。支持**配置模板化**、**权重分流**和**决策追踪**。

### 1.2 关键业务概念

| 概念 | 说明 | 类比 |
|------|------|------|
| **单据（document）** | 一份由多页组成的完整业务文件 | 一份发票有3页 |
| **字段（field）** | 需要从图片中提取的数据项 | invoice_number, amount |
| **模板（template）** | 提取方案的完整配置 | 每类单据的提取规则 |
| **前处理管道** | 对图片做的预处理（缩放/矫正/去噪） | OCR 前处理 |
| **后处理管道** | 对提取的值做处理（清洗/格式化） | 去除空格/转大写 |
| **聚合（aggregation）** | 跨页面合并同一个字段 | 发票号取第一页 |
| **权重分流** | 同一模板多版本按比例分配流量 | A/B 测试 |

---

## 二、分层架构总览

### 2.1 架构分层

```
┌───────────────────────────────────────────────────────────┐
│                      API 层                               │
│     ┌─────────────────────────────────────────────────┐  │
│     │  api/routers/extraction.py   (路由+参数校验)     │  │
│     │  routers/template_generator.py (路由+参数校验)    │  │
│     │  api/deps.py                (依赖注入)           │  │
│     └─────────────────────────────────────────────────┘  │
├───────────────────────────────────────────────────────────┤
│                      Service 层                           │
│     ┌─────────────────────────────────────────────────┐  │
│     │  extraction_service.py  (文档解析编排-核心)      │  │
│     │  config_service.py       (配置加载+模板选择)      │  │
│     │  db_service.py           (结果持久化)            │  │
│     │  aggregator_service.py   (跨页聚合)              │  │
│     │  template_generator_service.py (模板自动生成)     │  │
│     └─────────────────────────────────────────────────┘  │
├──────────────┬──────────────┬──────────────┬──────────────┤
│ Repository   │  Processor   │    Core      │    Utils     │
│ ─────────    │  ─────────   │  ─────────   │  ─────────   │
│ config_repo  │  pipeline    │  database    │  validator   │
│ extraction.. │  page_proc.. │  trace_mgr   │  version_h.. │
│ request_repo │  field_ext.. │  vlm_client  │              │
│              │  image_pre.. │              │              │
│              │  minio_upl.. │              │              │
└──────────────┴──────────────┴──────────────┴──────────────┘
                              │
        ┌─────────────────────┼─────────────────────┐
        ▼                     ▼                     ▼
      MySQL                MinIO                  VLM
```

### 2.2 依赖方向（红线）

```
API → Services → Repositories → Models
           ↘ Processors
           ↘ Core
```

**禁止逆向依赖**：Processors 不能调 Repositories，必须通过 Services 传递数据。

### 2.3 各层职责速查

| 层 | 目录 | 职责 | 禁止做的事 |
|----|------|------|-----------|
| **API** | `api/routers/` | 路由分发、参数校验、JSON 响应 | ❌ 业务逻辑、数据库操作 |
| **Service** | `services/` | 业务编排、事务边界、调用 Processor | ❌ 直接写 SQL |
| **Processor** | `processors/` | 文档处理管道（图片/字段/VLM） | ❌ 数据库操作 |
| **Repository** | `repositories/` | ORM 数据访问、CRUD | ❌ 业务逻辑、事务 commit |
| **Core** | `core/` | 基础设施（VLM 客户端/数据库连接） | ❌ 业务编排 |
| **Model** | `models/` | SQLAlchemy ORM 定义 | ❌ 业务方法 |
| **Schema** | `schemas/` | Pydantic 数据校验 | ❌ ORM 引用 |
| **Utils** | `utils/` | 纯函数工具（校验/版本生成） | ❌ IO 操作 |
| **Config** | `config/` | 应用配置管理 | — |

---

## 三、路由层（API Layer）

### 3.1 注册的路由

```python
app.include_router(extraction.router)      # POST /parse, GET /health, GET /state/{id}
app.include_router(template_generator.router)  # POST /generate_template
```

### 3.2 `POST /parse` — 文档解析（核心接口）

**请求**：
```http
POST /parse
Content-Type: multipart/form-data

doc_type: "letter_of_credit"
template_id: (可选，优先级高于 doc_type)
images: [file1, file2, ...]
```

**响应**：
```json
{
  "trace_id": "a1b2c3...",
  "fields": { "amount": 1000.0, "currency": "USD" },
  "warnings": [],
  "template": { "template_id": "lc_extraction", "version": "v1.0.0" },
  "elapsed": 2.5
}
```

**路由层做的事**（见 `extraction.py`）：

| 步骤 | 代码位置 | 说明 |
|------|---------|------|
| 参数校验 | `if doc_type is None and template_id is None` | 至少提供一个 |
| 追踪 | `trace_manager.new_trace()` | 生成 32 位 UUID |
| 图片读取 | `asyncio.gather(*read_tasks)` | 并行读所有图片 |
| 配置加载 | `await load_config(session, doc_type, template_id)` | 调 ConfigService |
| 前处理 | `execute_pre_process_pipeline(raw_bytes, pipeline)` | 调 Pipeline |
| 标准预处理 | `preprocess_image(processed, short_edge)` | 缩放 + JPEG 编码 |
| MinIO 上传 | `upload_to_minio(...)` | 并行上传 |
| 字段提取 | `process_page(b64, fields, page_num, vlm_config)` | 逐页串行 |
| 聚合 | `aggregate_results(all_page_results, agg_rules)` | 调 AggregatorService |
| 入库 | `save_results(session, ...)` | 调 DBService |

### 3.3 `POST /generate_template` — 模板自动生成

**请求**：
```http
POST /generate_template
Content-Type: multipart/form-data

files: [所有页面图片（按页码顺序）]
doc_type: "invoice"
template_id: (可选，不提供则自动生成)
version: (可选，如 "v1.0.0")
```

**响应**：
```json
{
  "template_id": "invoice_default_20250605143000",
  "template_version": "v1.0.0",
  "doc_type": "invoice",
  "fields_config_id": 101,
  "profile_config_id": 102,
  "aggregation_config_id": 103,
  "message": "Template created successfully"
}
```

**生成流程**：
1. 读取并预处理所有图片（缩放至短边 1024px）
2. 调用 VLM 生成 **fields 配置**（全局字段定义）
3. 调用 VLM 生成 **profile 配置**（字段提取策略）
4. 调用 VLM 生成 **aggregation 配置**（聚合规则）
5. 校验配置 → 写入 `config_versions`（3 条记录）
6. 计算版本号 → 写入 `config_templates`（1 条记录）
7. 事务提交

### 3.4 辅助端点

```http
GET /health              # 健康检查，返回 traces_count
GET /state/{trace_id}    # 查询请求处理状态（pending→preprocessing→...→completed）
```

### 3.5 依赖注入（`api/deps.py`）

```python
get_db() -> AsyncSession        # 数据库会话
get_vlm_config() -> dict        # VLM 配置（endpoint/model/api_key...）
get_minio_config() -> dict      # MinIO 配置（endpoint/bucket...）
get_image_config() -> dict      # 图片处理配置（target_short_edge）
get_trace_mgr() -> TraceManager # 追踪管理器单例
```

---

## 四、服务层（Service Layer）

### 4.1 `ConfigService` — 配置加载与模板选择

文件：`services/config_service.py`

**业务流程图**：
```
load_config(doc_type, template_id)
  │
  ├─ resolve_template()          确定使用哪个 template_id
  │   ├─ force_template_id 优先
  │   ├─ doc_type → DEFAULT_TEMPLATE_MAP
  │   └─ doc_type → 查表回退
  │
  ├─ select_template()           按权重随机选版本
  │   ├─ 权重总和=100 → 加权随机
  │   ├─ 权重总和=0 → 均等随机
  │   └─ 记录分流决策追踪
  │
  └─ get_config_by_id() ×3      加载 fields / profile / aggregation
```

**核心函数**：

| 函数 | 参数 | 返回值 | 说明 |
|------|------|--------|------|
| `load_config()` | session, doc_type, template_id | `{fields_schema, profile, agg_rules, template, trace}` | 完整配置加载 |
| `resolve_template()` | session, doc_type, force_template_id | `(template_dict, trace)` | 解析最终 template_id |
| `select_template()` | session, template_id | `(template, trace)` | 按权重分流选择 |
| `get_config_by_id()` | session, config_id | `dict` | 按 ID 取配置内容 |
| `get_active_templates()` | session, template_id, doc_type | `list[dict]` | 查激活模板 |

**默认 doc_type→template_id 映射**：
```python
DEFAULT_TEMPLATE_MAP = {
    "letter_of_credit": "lc_extraction",
    "invoice": "invoice_extraction",
}
```

**权重分流决策追踪示例**（存到 requests.trace 字段）：
```json
{
  "candidates": [{"version": "v1.0.0", "weight": 70}, {"version": "v2.0.0", "weight": 30}],
  "weights": [70, 30],
  "total_weight": 100,
  "random_value": 55,
  "selected_index": 0,
  "selected_version": "v1.0.0",
  "doc_type": "invoice",
  "fallback_used": false
}
```

### 4.2 `DBService` — 结果持久化

文件：`services/db_service.py`

写入三张表，在一个事务中完成：

```
save_results()
  ├─ _insert_request()
  │   └─ INSERT INTO requests (trace_id, doc_type, total_pages, final_fields,
  │       warnings, template_id, template_version, selected_weight, trace)
  │
  ├─ _insert_field_extractions()
  │   └─ INSERT INTO field_extractions (trace_id, page_num, field_name, ...)
  │      批量写入
  │
  ├─ _insert_agg_decisions()
  │   └─ INSERT INTO agg_decisions (trace_id, field_name, selected_page, ...)
  │      批量写入
  │
  └─ session.commit() / session.rollback()
```

### 4.3 `AggregatorService` — 跨页字段聚合

文件：`services/aggregator_service.py`

**聚合流程**：
```
aggregate_results(all_page_results, agg_rules)
  │
  ├─ 步骤1：按 field_name 重新组织数据
  │   └─ {field_name: [{page, value, confidence}, ...]}
  │
  └─ 步骤2：对每个字段应用聚合策略
      ├─ first_non_null   取第一个非空值（默认）
      ├─ last_non_null    取最后一个非空值
      ├─ max_confidence   取置信度最高值
      └─ merge_lists      合并所有页的列表
```

**策略用法示例**：
```json
{
  "invoice_number": { "strategy": "first_non_null" },
  "item_descriptions": { "strategy": "merge_lists" },
  "total_amount": { "strategy": "last_non_null" },
  "default": { "strategy": "first_non_null" }
}
```

### 4.4 `TemplateGeneratorService` — 模板自动生成

文件：`services/template_generator_service.py`

**三种 VLM 提示词**：

1. **fields 配置** — 分析图片识别所有字段，输出 `{fields: {field_name: {type, description}}}`
2. **profile 配置** — 分析图片+字段名，输出 `{doc_type, fields: {field_name: {prompt_hint, pages}}}`
3. **aggregation 配置** — 基于字段名，输出 `{fields: {field_name: {strategy}}}`

**校验链**（`utils/validator.py`）：
- `validate_fields_config()` — 必须有 fields 对象，每个 field 必须有 type
- `validate_profile_config()` — doc_type 一致，fields 结构正确
- `validate_aggregation_config()` — 策略名合法，字段名在 profile 中存在

---

## 五、处理器层（Processor Layer）

### 5.1 `Pipeline` — 前/后处理管道

文件：`processors/pipeline.py`

**管道语法**：用 `|` 连接步骤，支持参数 `func_name` 或 `func_name(arg1,arg2)`

**前处理函数（7 个）**：

| 函数 | 参数 | 说明 |
|------|------|------|
| `fix_orientation` | — | 根据 EXIF 修正方向（预留占位） |
| `deskew` | — | 霍夫变换倾斜矫正 |
| `denoise` | — | 非局部均值去噪 |
| `scale` | `short_edge` | 缩放短边到指定像素（默认 1024） |
| `crop` | `x1,y1,x2,y2` | 裁剪（支持 0-1 百分比或像素值） |
| `to_grayscale` | — | 转灰度图 |
| `enhance_contrast` | — | CLAHE 自适应对比度增强 |

**配置示例（存于 config_templates.pre_process 字段）**：
```
fix_orientation|deskew|scale(1024)
denoise|enhance_contrast|scale(800)
crop(0.1,0.1,0.9,0.9)|to_grayscale
```

**后处理函数（8 个）**：

| 函数 | 参数 | 说明 |
|------|------|------|
| `strip` | — | 去除首尾空白 |
| `lower` | — | 转小写 |
| `upper` | — | 转大写 |
| `to_number` | — | 转数字（自动去除千分位逗号） |
| `to_string` | — | 强转字符串 |
| `json_parse` | — | JSON 字符串解析为对象 |
| `round` | `decimals` | 数字四舍五入（默认 0 位） |
| `replace` | `old, new` | 子串替换（默认去空格） |

**配置示例（存于 profile.fields 的 post_process 字段）**：
```
strip|to_number|round(2)
strip|upper
json_parse
```

**管道执行流程**：
```python
# 前处理：image_bytes → 解码为 ndarray → 每步处理 → 编码回 JPEG
execute_pre_process_pipeline(image_bytes, "deskew|scale(1024)")

# 后处理：原始值 → 每步处理 → 最终值
execute_post_process_pipeline("  abc  ", "strip|upper")  # → "ABC"
```

### 5.2 `ImagePreprocess` — 标准图像预处理

文件：`processors/image_preprocess.py`

```python
preprocess_image(image_bytes, target_short_edge=1024) -> bytes
# 缩放后编码为 JPEG（质量 85）

encode_to_base64(image_bytes) -> str
# → "data:image/jpeg;base64,/9j/4AAQ..."
```

### 5.3 `PageProcessor` — 单页字段提取

文件：`processors/page_processor.py`

**串行提取流程**：
```
process_page(image_base64, fields_config, page_num, vlm_config)
  │
  └─ for each field in fields_config:
      ├─ extract_field(image, field_cfg, vlm_config)
      │   └─ call_vlm() → _parse_response()  → (value, confidence, raw)
      ├─ execute_post_process_pipeline(value, post_process)  # 如有配置
      └─ 记录结果 / 错误容忍
```

**容错机制**：单个字段 VLM 调用失败不会中断整页，返回 `{value: None, confidence: 0.0}` 继续处理下一个字段。

### 5.4 `FieldExtractor` — 字段值解析

文件：`processors/field_extractor.py`

**解析规则**：

| 字段类型 | 解析方式 | 重试机制 |
|---------|---------|---------|
| `string` | 直接去首尾空白 | — |
| `number` | `float()` 转换，自动去千分位逗号 | — |
| `list` | `json.loads()` 解析 JSON 数组 | JSON 解析失败则重试（强调 JSON 格式） |
| `object` | `json.loads()` 解析 JSON 对象 | JSON 解析失败则重试（强调 JSON 格式） |

### 5.5 `MinioUpload` — 异步图片存储

文件：`processors/minio_upload.py`

```python
upload_to_minio(image_bytes, bucket, object_name, endpoint, ...) -> str
# 返回 "bucket/object_name"
# 自动创建 bucket（如不存在）
# 使用 asyncio.to_thread 包装同步 MinIO 客户端
```

存储路径格式：`{bucket}/{trace_id}/page_{n}.jpg`

---

## 六、仓储层（Repository Layer）

### 6.1 三层仓库

| 仓库 | 文件 | 管理的表 | 核心方法 |
|------|------|---------|---------|
| `ConfigRepository` | `repositories/config_repo.py` | `config_versions`, `config_templates` | get/check/insert 配置版本和模板 |
| `ExtractionRepository` | `repositories/extraction_repo.py` | `field_extractions`, `agg_decisions` | 单条/批量插入，按 trace_id 查询 |
| `RequestRepository` | `repositories/request_repo.py` | `requests` | insert/update/delete，按类型列表查询 |

**注意**：当前 DBService 直接使用 `text()` SQL 写入，未使用 Repository 层。Repository 层已定义但未被 Service 层调用——这是待优化点。

---

## 七、核心层（Core Layer）

### 7.1 `Database` — 连接管理

文件：`core/database.py`

```python
from config.settings import settings

engine = create_async_engine(settings.get_db_url(), echo=debug)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)

init_database()   # 启动时调用，SELECT 1 测试连接
close_database()  # 关闭时调用，engine.dispose()
```

### 7.2 `TraceManager` — 请求追踪

文件：`core/trace_manager.py`

**状态流转**：
```
pending → preprocessing → loading_config → preprocessing → uploading
  → extracting → aggregating → saving → completed
                                       → error
```

**状态记录示例**：
```python
trace_manager.update_state(trace_id, {"status": "extracting", "current_page": 3})
```

**全局单例**：`get_trace_manager() → TraceManager`

### 7.3 `VLMClient` — 视觉大模型调用

文件：`core/vlm_client.py`

**API 格式**：OpenAI 多模态聊天补全格式兼容

```python
call_vlm(
    image_base64,     # "data:image/jpeg;base64,..."
    user_prompt,      # "请提取字段 'invoice_number'..."
    endpoint,         # VLM 服务地址
    model,            # "qwen-vl-max"
    api_key,
    max_tokens,       # None 表示不限制
    temperature,      # 0.0
    max_retries,      # 2（指数退避重试）
    timeout,          # 30.0
    enable_thinking,  # True/False
    system_prompt,    # 可选覆盖
) -> (response_text, confidence)
```

**默认系统提示词**：
```
你是一个单据解析专家。每次只提取一个字段，只输出字段值，
不要输出任何额外文字。如果字段不存在，输出空字符串。
```

---

## 八、数据模型层（Models + Schemas）

### 8.1 数据库表结构

**5 张表**：

```
config_versions    配置版本（fields / profile / aggregation）
config_templates   配置模板（组合三个配置版本，支持权重）
requests           请求主表（含最终结果 + 分流追踪）
field_extractions  字段提取明细（每页每个字段）
agg_decisions      聚合决策记录（每个字段的聚合过程）
```

**表关系**：
```
config_templates
  ├── fields_config_id ──→ config_versions (config_type=fields)
  ├── profile_config_id ──→ config_versions (config_type=profile)
  └── aggregation_config_id ──→ config_versions (config_type=aggregation)

requests
  └── trace_id  ──→ field_extractions.trace_id
                  ──→ agg_decisions.trace_id
```

### 8.2 关键数据库字段

**requests.trace** — 分流决策追踪（JSON）：
```json
{
  "doc_type": "invoice",
  "resolved_template_id": "invoice_extraction",
  "selected_version": "v2.0.0",
  "candidates": [{"version": "v1.0.0", "weight": 70}, ...],
  "random_value": 55,
  "total_weight": 100,
  "warning": null
}
```

### 8.3 ORM 模型（`models/`）

| 文件 | 模型类 | 对应表 |
|------|--------|--------|
| `base.py` | `Base` | — |
| `config.py` | `ConfigVersion`, `ConfigTemplate` | `config_versions`, `config_templates` |
| `request.py` | `Request`, `FieldExtraction`, `AggDecision` | `requests`, `field_extractions`, `agg_decisions` |

### 8.4 Pydantic Schema（`schemas/`）

| 文件 | 核心模型 |
|------|---------|
| `config.py` | `ConfigVersionResponse`, `ConfigTemplateResponse`, `LoadedConfig`, `ResolveTrace` |
| `extraction.py` | `ParseResponse`, `ParseErrorResponse`, `ExtractionDetail`, `FieldResult` |
| `template.py` | `GenerateTemplateResponse`, `FieldDefinition`, `ProfileFieldConfig`, `AggregationRule` |

---

## 九、配置层（Config Layer）

### 9.1 环境变量

文件：`config/settings.py`（Pydantic Settings）

```env
# VLM
VLM_ENDPOINT=http://gateway/v1/chat/completions
VLM_MODEL=qwen-vl-max
VLM_API_KEY=xxx
VLM_MAX_TOKENS=      # 空或-1表示不限制
VLM_TEMPERATURE=0.0
VLM_TIMEOUT=30.0
VLM_MAX_RETRIES=2
VLM_ENABLE_THINKING=false

# MinIO
MINIO_ENDPOINT=localhost:9000
MINIO_ACCESS_KEY=admin
MINIO_SECRET_KEY=xxx
MINIO_BUCKET=philsee-images
MINIO_SECURE=false

# MySQL
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=root
MYSQL_PASSWORD=xxx
MYSQL_DATABASE=philsee

# Image
IMAGE_TARGET_SHORT_EDGE=1024
```

### 9.2 配置使用方法

```python
from config.settings import settings

settings.get_db_url()       # → "mysql+aiomysql://..."
settings.get_vlm_config()   # → {endpoint, model, api_key, ...}
settings.get_minio_config() # → {endpoint, access_key, ...}
```

---

## 十、工具层（Utils）

### 10.1 `Validator`（`utils/validator.py`）

| 函数 | 用途 | 校验规则 |
|------|------|---------|
| `validate_fields_config()` | fields 配置校验 | 有 fields 对象，每个字段有 type |
| `validate_profile_config()` | profile 配置校验 | doc_type 一致，有 fields 对象 |
| `validate_aggregation_config()` | aggregation 配置校验 | 策略合法，字段在 profile 中存在 |
| `extract_profile_field_names()` | 提取字段名列表 | — |

**有效字段类型**：`string`, `number`, `date`, `list`, `object`, `boolean`
**有效聚合策略**：`first`, `last`, `concat`, `max`, `min`, `sum`, `latest`, `earliest`

### 10.2 `VersionHelper`（`utils/version_helper.py`）

| 函数 | 用途 |
|------|------|
| `generate_default_template_id(doc_type)` | `{doc_type}_default_{timestamp}` |
| `generate_template_version(session, template_id, version?)` | 自增 v1.0.0→v1.0.1→... |
| `check_config_version_exists(session, ...)` | 检查唯一约束 |
| `insert_config_version(session, ...)` | 插入配置版本，返回 ID |
| `check_template_exists(session, template_id, version)` | 检查模板是否已存在 |
| `insert_template(session, ...)` | 插入模板记录，返回 ID |

---

## 十一、完整数据流用例

### 用例 1：解析一份 3 页单据

```bash
# 请求
curl -X POST http://localhost:8000/parse \
  -F "doc_type=letter_of_credit" \
  -F "images=@page1.jpg" \
  -F "images=@page2.jpg" \
  -F "images=@page3.jpg"
```

**内部执行时序**：
```
1. trace_manager.new_trace()              → trace_id: "a1b2c3..."
2. 并行读取 3 张图片
3. ConfigService.load_config()            → 按权重选版本，加载三个配置
   ├─ resolve_template("letter_of_credit")  → template_id="lc_extraction"
   ├─ select_template("lc_extraction")       → version="v2.0.0" (权重 70/30)
   └─ get_config_by_id() ×3                 → fields_schema, profile, agg_rules
4. 并行前处理: pre_process_pipeline → preprocess_image → encode_to_base64
5. 并行上传到 MinIO: bucket/a1b2c3/page_1.jpg
6. 逐页提取 (串行，利用前缀缓存):
   ├─ Page 1: extract_field(invoice_number), extract_field(amount)
   ├─ Page 2: extract_field(amount)
   └─ Page 3: extract_field(total_amount)
7. AggregatorService.aggregate_results()
   ├─ 策略: invoice_number=first_non_null → page 1
   ├─ 策略: amount=first_non_null         → page 1
   └─ 策略: total_amount=last_non_null    → page 3
8. DBService.save_results() → 写入 3 张表 (事务)
9. 返回 {trace_id, fields, template, elapsed}
```

### 用例 2：自动生成模板

```bash
# 请求
curl -X POST http://localhost:8000/generate_template \
  -F "files=@sample_page1.jpg" \
  -F "files=@sample_page2.jpg" \
  -F "doc_type=invoice"
```

**内部时序**：
```
1. 读取并预处理样本图片
2. VLM: "请分析以下 2 张图片..." → fields 配置（15 个字段）
3. VLM: "请根据图片和字段..." → profile 配置（含 prompt_hint + pages）
4. VLM: "请根据字段列表..." → aggregation 配置（含策略）
5. 校验三套配置
6. 写入 config_versions × 3（同一事务）
7. 计算版本号 v1.0.0
8. 写入 config_templates（同一事务）
9. 提交事务，返回模板信息
```

---

## 十二、开发与部署

### 12.1 启动命令

```bash
# 开发模式（热重载）
uvicorn online.main:app --reload --port 8000

# 生产模式
uvicorn online.main:app --host 0.0.0.0 --port 8000 --workers 4
```

### 12.2 数据库初始化

```bash
mysql -u root -p < sql/init_db.sql
```

初始化脚本会重建 5 张表（DROP IF EXISTS + CREATE）。

### 12.3 运行测试

```bash
pytest tests/
```

当前测试覆盖：19 个 test function，仅覆盖 `POST /generate_template`。

### 12.4 类型检查

```bash
mypy online/
```

---

## 十三、架构分析：当前问题与建议

### 已知问题

| 问题 | 影响 | 建议 |
|------|------|------|
| DBService 使用 `text()` SQL 而非 Repository 层 | **已修复** ✅ | 已接入 Repository |
| `_get_fields_for_page()` 重复 | **已修复** ✅ | 已移至 ExtractionService |
| 路由层直调 pipeline | **已修复** ✅ | 已下沉至 ExtractionService |
| 测试覆盖率仍偏低（38 个） | 质量风险 | 补 `/parse` 集成测试 |
| `async for ... break` session 模式 | 事务不够优雅 | 未来可改为 context manager |

### 扩展建议

**添加新功能的标准检查清单**：
- [ ] 路由放在 `api/routers/`
- [ ] 业务逻辑放在 `services/`
- [ ] 数据库操作放在 `repositories/`
- [ ] 新表需要 `models/` 和对应的 `schemas/`
- [ ] 配置项通过 `config/settings.py` 管理
- [ ] 处理管道放在 `processors/`（如需新增前/后处理函数，注册到 `pipeline.py` 的 `PRE_PROCESSORS`/`POST_PROCESSORS` 字典）