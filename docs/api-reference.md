# API 参考

本文档描述 Philsee 提供的所有 API 接口。

## 基础信息

- **Base URL**: `http://localhost:8000`
- **Content-Type**: `multipart/form-data` (上传文件) 或 `application/json`
- **认证**: 无（开发环境）

## 接口列表

### POST /parse

解析单据文档，提取指定字段。

**请求参数** (multipart/form-data):

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `doc_type` | string | 二选一 | 单据类型（如 `letter_of_credit`） |
| `template_id` | string | 二选一 | 模板编号（优先级高于 doc_type） |
| `images` | file[] | 是 | 图片文件列表（按页码顺序） |

**示例请求**:

```bash
# 使用 doc_type
curl -X POST "http://localhost:8000/parse" \
  -F "doc_type=letter_of_credit" \
  -F "images=@page1.jpg" \
  -F "images=@page2.jpg"

# 使用 template_id
curl -X POST "http://localhost:8000/parse" \
  -F "template_id=lc_extraction" \
  -F "images=@page1.jpg" \
  -F "images=@page2.jpg"
```

**成功响应** (200):

```json
{
  "trace_id": "a1b2c3d4e5f6...",
  "fields": {
    "lc_number": "LC123456789",
    "amount": 10000.00,
    "currency": "USD",
    "date": "2024-01-15"
  },
  "warnings": [],
  "template": {
    "template_id": "lc_extraction",
    "version": "v1.0.0",
    "weight": 100
  },
  "elapsed": 12.34
}
```

**错误响应**:

| 状态码 | 说明 |
|--------|------|
| 400 | 参数错误（未提供 doc_type 或 template_id） |
| 404 | 配置或模板不存在 |
| 500 | 处理失败 |

---

### POST /generate_template

根据样例图片自动生成模板配置。

**请求参数** (multipart/form-data):

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `files` | file[] | 是 | 样例图片（按页码顺序） |
| `doc_type` | string | 是 | 文档类型 |
| `template_id` | string | 否 | 模板编号（不提供则自动生成） |
| `version` | string | 否 | 模板版本（不提供则自动递增） |

**示例请求**:

```bash
curl -X POST "http://localhost:8000/generate_template" \
  -F "files=@sample1.jpg" \
  -F "files=@sample2.jpg" \
  -F "doc_type=invoice"
```

**成功响应** (200):

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

**错误响应**:

| 状态码 | 说明 |
|--------|------|
| 400 | 参数错误 |
| 409 | template_id 已存在 |
| 500 | 生成失败 |

---

### GET /health

健康检查接口。

**示例请求**:

```bash
curl http://localhost:8000/health
```

**响应**:

```json
{
  "status": "healthy",
  "traces_count": 0
}
```

---

### GET /state/{trace_id}

查询请求处理状态。

**示例请求**:

```bash
curl http://localhost:8000/state/a1b2c3d4e5f6...
```

**成功响应** (200):

```json
{
  "trace_id": "a1b2c3d4e5f6...",
  "state": {
    "status": "completed",
    "fields": {...},
    "elapsed": 12.34
  }
}
```

**错误响应**:

| 状态码 | 说明 |
|--------|------|
| 404 | trace_id 不存在 |

---

## OpenAPI 文档

启动服务后访问：

- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`
- OpenAPI JSON: `http://localhost:8000/openapi.json`
