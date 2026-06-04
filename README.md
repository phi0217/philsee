# Philsee - 智能单据解析服务

Philsee 是一个基于 FastAPI 的智能单据解析服务，支持多页文档的字段提取、跨页聚合和结果存储。

## 功能特性

- **多页文档处理**：支持上传多张图片，自动按页处理
- **字段智能提取**：使用 VLM（视觉大模型）提取指定字段
- **跨页聚合**：支持多种聚合策略（first_non_null, last_non_null, max_confidence, merge_lists）
- **异步处理**：全异步架构，高性能处理
- **配置版本化**：支持配置版本管理，灵活切换

## 目录结构

```
philsee/
├── online/                     # 主代码包
│   ├── __init__.py
│   ├── image_preprocess.py     # 图像预处理
│   ├── minio_upload.py         # MinIO 上传
│   ├── config_loader.py        # 配置加载
│   ├── vlm_client.py           # VLM 客户端
│   ├── field_extractor.py      # 字段提取
│   ├── page_processor.py       # 单页处理
│   ├── aggregator.py           # 跨页聚合
│   ├── db_writer.py            # 数据库写入
│   ├── trace_manager.py        # 请求追踪
│   └── main_api.py             # FastAPI 入口
├── sql/
│   └── init_db.sql             # 数据库初始化脚本
├── .env.example                # 环境变量模板
├── requirements.txt            # 依赖列表
└── README.md                   # 说明文档
```

## 环境准备

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置环境变量

```bash
# 复制模板
cp .env.example .env

# 编辑 .env 文件，填写真实的连接信息
vim .env
```

### 3. 启动外部服务

**注意：本项目不提供 docker-compose.yml，请自行启动 MySQL 和 MinIO 服务。**

#### MySQL

```bash
# 使用 Docker 启动 MySQL
docker run -d \
  --name philsee-mysql \
  -e MYSQL_ROOT_PASSWORD=password \
  -e MYSQL_DATABASE=philsee \
  -p 3306:3306 \
  mysql:8.0 \
  --character-set-server=utf8mb4 \
  --collation-server=utf8mb4_unicode_ci
```

#### MinIO

```bash
# 使用 Docker 启动 MinIO
docker run -d \
  --name philsee-minio \
  -e MINIO_ROOT_USER=admin \
  -e MINIO_ROOT_PASSWORD=admin123456 \
  -p 9000:9000 \
  -p 9001:9001 \
  minio/minio server /data --console-address ":9001"
```

### 4. 初始化数据库

```bash
# 执行数据库初始化脚本
mysql -h localhost -u root -p < sql/init_db.sql
```

## 运行服务

```bash
# 开发模式（带热重载）
uvicorn online.main_api:app --reload --port 8000

# 生产模式
uvicorn online.main_api:app --host 0.0.0.0 --port 8000 --workers 4
```

## API 接口

### POST /parse

解析单据文档。

**请求参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| doc_type | string | 是 | 单据类型（如 `letter_of_credit`） |
| images | file[] | 是 | 图片文件列表 |

**示例请求：**

```bash
curl -X POST "http://localhost:8000/parse" \
  -F "doc_type=letter_of_credit" \
  -F "images=@page1.jpg" \
  -F "images=@page2.jpg"
```

**响应示例：**

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
  "elapsed": 12.34
}
```

### GET /health

健康检查接口。

```bash
curl http://localhost:8000/health
```

### GET /state/{trace_id}

查询请求处理状态。

```bash
curl http://localhost:8000/state/a1b2c3d4e5f6...
```

## 配置说明

### 配置结构

系统配置存储在 MySQL 的 `config_versions` 表中，包含三种类型：

1. **fields** - 全局字段定义（定义字段名称和类型）
2. **profile** - 单据类型的字段策略（定义提取规则）
3. **aggregation** - 聚合规则（定义跨页合并策略）

### 聚合策略

| 策略 | 说明 |
|------|------|
| `first_non_null` | 按页码顺序取第一个非空值 |
| `last_non_null` | 按页码顺序取最后一个非空值 |
| `max_confidence` | 取置信度最高的值 |
| `merge_lists` | 合并所有页的列表 |

## 开发说明

### 模块依赖关系

```
main_api.py
├── image_preprocess.py
├── minio_upload.py
├── config_loader.py
├── page_processor.py
│   └── field_extractor.py
│       └── vlm_client.py
├── aggregator.py
├── db_writer.py
└── trace_manager.py
```

### 日志格式

日志包含以下信息：
- 时间戳
- 模块名称
- 日志级别
- 文件名和行号
- trace_id（用于追踪请求）

## 故障排查

### 常见问题

1. **数据库连接失败**
   - 检查 MySQL 是否启动
   - 确认 `.env` 中的数据库配置正确

2. **MinIO 上传失败**
   - 检查 MinIO 是否启动
   - 确认 bucket 是否存在或有权创建

3. **VLM 调用失败**
   - 检查 VLM_ENDPOINT 是否正确
   - 确认 API Key 有效

## License

MIT License
