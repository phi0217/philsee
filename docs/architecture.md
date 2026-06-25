# 系统架构

本文档详细说明 Philsee 的系统架构、数据流和设计决策。

## 整体架构

Philsee 是一个智能单据解析服务，采用分层架构设计：

```
┌─────────────────────────────────────────────────────────────┐
│                        API Layer                             │
│                    (api/routers/)                            │
├─────────────────────────────────────────────────────────────┤
│                      Service Layer                           │
│                     (services/)                              │
├──────────────┬──────────────┬──────────────┬────────────────┤
│ Repositories │  Processors  │    Core      │    Models      │
│              │              │              │                │
│ (data access)│ (pipeline)   │ (infra)      │ (ORM)          │
└──────────────┴──────────────┴──────────────┴────────────────┘
                              │
              ┌───────────────┼───────────────┐
              ▼               ▼               ▼
           MySQL           MinIO            VLM
```

## 核心数据流

### 文档解析流程

```
POST /parse (images + doc_type/template_id)
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. 配置加载 (ConfigService)                                  │
│    - 解析 template_id 或通过 doc_type 映射                   │
│    - 按权重选择模板版本                                      │
│    - 加载 fields, profile, aggregation 配置                 │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. 处理管道 (Pipeline)                                       │
│    a. ImagePreprocess: 缩放、base64 编码                     │
│    b. MinIO Upload: 存储原图                                 │
│    c. PageProcessor: 逐页提取字段                            │
│       └── FieldExtractor → VLMClient                        │
│    d. Aggregator: 跨页聚合                                   │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. 结果存储 (DBService)                                      │
│    - 写入 requests 主表                                      │
│    - 写入 field_extractions 明细                             │
│    - 写入 agg_decisions 聚合决策                             │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
返回 JSON 结果
```

### 模板生成流程

```
POST /generate_template (images + doc_type)
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. 图片预处理                                                │
│    - 缩放、base64 编码，保持页码顺序                         │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. VLM 生成配置                                              │
│    a. 生成 fields: 全局字段定义                              │
│    b. 生成 profile: 字段提取策略                             │
│    c. 生成 aggregation: 跨页聚合策略                         │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. 数据库写入 (事务)                                         │
│    - 插入 config_versions (3条记录)                          │
│    - 插入 config_templates (1条记录)                         │
└─────────────────────────────────────────────────────────────┘
    │
    ▼
返回模板信息
```

## 配置模板机制

### 两表设计

系统采用 **config_versions + config_templates** 两表设计：

**config_versions**: 存储配置的原始版本
- `doc_type`: `*`（全局）或具体类型
- `config_type`: `fields` / `profile` / `aggregation`
- `version_tag`: 版本标识
- `content`: JSON 配置内容

**config_templates**: 组合配置形成模板
- `template_id`: 模板业务编号
- `version`: 模板版本号
- `fields_config_id`: 关联 fields 配置
- `profile_config_id`: 关联 profile 配置
- `aggregation_config_id`: 关联 aggregation 配置
- `weight`: 分流权重 (0-100)

### 权重分流

当同一 `template_id` 下有多个激活版本时，系统按权重随机选择：

```python
# 示例：A/B 测试
# v1.0.0 权重 80%，v2.0.0 权重 20%
candidates = [
    {"version": "v1.0.0", "weight": 80},
    {"version": "v2.0.0", "weight": 20}
]
random_value = random.randint(1, 100)  # 例如 65
# 65 <= 80，选择 v1.0.0
```

决策过程记录在 `requests.trace` 字段：

```json
{
  "doc_type": "letter_of_credit",
  "resolved_template_id": "lc_extraction",
  "candidates": [...],
  "random_value": 65,
  "selected_version": "v1.0.0"
}
```

### 配置类型说明

**fields**: 全局字段定义
```json
{
  "fields": {
    "amount": {"type": "number"},
    "currency": {"type": "string"},
    "date": {"type": "date"}
  }
}
```

**profile**: 字段提取策略
```json
{
  "doc_type": "invoice",
  "fields": {
    "amount": {
      "prompt_hint": "发票金额，通常在右下角",
      "pages": "all"
    }
  }
}
```

**aggregation**: 跨页聚合策略
```json
{
  "amount": {"strategy": "max_confidence"},
  "date": {"strategy": "first_non_null"}
}
```

## 聚合策略

| 策略 | 说明 | 适用场景 |
|------|------|----------|
| `first_non_null` | 取第一个非空值 | 单次出现的字段 |
| `last_non_null` | 取最后一个非空值 | 可能被更新的字段 |
| `max_confidence` | 取置信度最高的值 | 需要高准确性的字段 |
| `merge_lists` | 合并所有列表 | 多页列表字段 |

## 依赖注入

系统使用 FastAPI 的依赖注入机制：

```python
# online/api/deps.py (示例)

async def get_db() -> AsyncGenerator[AsyncSession, None]:
    async with AsyncSessionLocal() as session:
        yield session

@lru_cache
def get_settings() -> Settings:
    return Settings()
```

路由中使用：

```python
@router.post("/parse")
async def parse(
    files: List[UploadFile],
    doc_type: str = Form(None),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings)
):
    ...
```

## 错误处理

系统采用统一错误响应格式：

```json
{
  "detail": "错误描述",
  "error_code": "CONFIG_NOT_FOUND",
  "trace_id": "xxx"
}
```

常见错误码：
- `CONFIG_NOT_FOUND`: 配置或模板不存在
- `TEMPLATE_CONFLICT`: template_id 已存在 (409)
- `VLM_ERROR`: VLM 调用失败
- `STORAGE_ERROR`: MinIO 存储失败

## 性能考虑

1. **异步架构**: 所有 I/O 操作使用 async/await
2. **连接池**: 数据库连接复用
3. **批量处理**: 多页文档并行处理（可配置串行）
4. **缓存策略**: 配置缓存（待实现）
