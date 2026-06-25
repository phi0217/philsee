# Philsee - 智能单据解析服务

Philsee 是一个基于 FastAPI 的智能单据解析服务，支持多页文档的字段提取、跨页聚合和结果存储。

## 功能特性

- **多页文档处理**：支持上传多张图片，自动按页处理
- **字段智能提取**：使用 VLM（视觉大模型）提取指定字段
- **跨页聚合**：支持多种聚合策略（first_non_null, last_non_null, max_confidence, merge_lists）
- **异步处理**：全异步架构，高性能处理
- **配置模板化**：通过模板组合管理配置，支持版本控制
- **权重分流**：支持按权重随机选择模板版本，便于 A/B 测试
- **决策追踪**：记录详细的分流决策过程，便于调试和分析

## 目录结构

```
philsee/
├── online/                     # 主代码包（分层架构）
│   ├── api/                    # API 层
│   │   └── routers/            # 路由模块
│   │       └── extraction.py   # 文档解析接口
│   ├── services/               # 服务层（业务逻辑）
│   │   ├── config_service.py   # 配置加载服务
│   │   ├── aggregator_service.py
│   │   ├── db_service.py
│   │   └── template_generator_service.py
│   ├── models/                 # 数据库模型层（SQLAlchemy ORM）
│   │   ├── config.py           # config_versions、config_templates 模型
│   │   └── request.py          # requests 模型
│   ├── schemas/                # Pydantic 模型（请求/响应结构）
│   ├── repositories/           # 数据访问层
│   │   ├── config_repo.py
│   │   ├── request_repo.py
│   │   └── extraction_repo.py
│   ├── core/                   # 核心组件
│   │   ├── database.py         # 数据库连接管理
│   │   ├── vlm_client.py       # VLM 客户端
│   │   └── trace_manager.py    # 追踪管理器
│   ├── processors/             # 处理器模块
│   │   ├── image_preprocess.py # 图像预处理
│   │   ├── page_processor.py   # 页面处理器
│   │   ├── field_extractor.py  # 字段提取器
│   │   ├── aggregator.py       # 聚合器
│   │   └── pipeline.py         # 处理管道
│   ├── utils/                  # 工具函数
│   ├── main.py                 # FastAPI 应用入口
│   └── main_api.py             # 旧入口（已废弃，保留兼容）
├── config/                     # 配置管理
│   └── settings.py             # Pydantic Settings 配置
├── sql/
│   └── init_db.sql             # 数据库初始化脚本
├── develop/                    # 开发辅助
│   ├── doc/                    # 设计文档
│   ├── prompt/                 # 开发提示词（历史记录）
│   └── script/                 # 开发脚本
├── tests/                      # 测试目录
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
| doc_type | string | 二选一 | 单据类型（如 `letter_of_credit`） |
| template_id | string | 二选一 | 模板编号（优先级高于 doc_type） |
| images | file[] | 是 | 图片文件列表 |

**示例请求：**

```bash
# 使用 doc_type（会自动映射到默认模板）
curl -X POST "http://localhost:8000/parse" \
  -F "doc_type=letter_of_credit" \
  -F "images=@page1.jpg" \
  -F "images=@page2.jpg"

# 使用 template_id（指定具体模板）
curl -X POST "http://localhost:8000/parse" \
  -F "template_id=lc_extraction" \
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
  "template": {
    "template_id": "lc_extraction",
    "version": "v1.0.0",
    "weight": 100
  },
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

### 配置架构（v2.0）

系统采用**配置模板化**架构，包含以下核心表：

| 表名 | 说明 |
|------|------|
| `config_versions` | 配置版本表，存储 fields、profile、aggregation 配置的历史版本 |
| `config_templates` | 配置模板表，组合三个配置版本，支持权重分流 |

### 配置类型

1. **fields** - 全局字段定义
   - 定义字段名称和类型
   - `doc_type` 固定为 `*`（全局）

2. **profile** - 字段策略配置
   - 定义每种文档类型的字段提取规则
   - 包含 `prompt_hint`（提示词）和 `pages`（提取页码策略）

3. **aggregation** - 聚合规则
   - 定义跨页合并策略

### 模板管理

模板（`config_templates`）将三种配置组合在一起：

```sql
-- 示例：信用证解析模板
INSERT INTO config_templates (
    template_id, version, doc_type, description,
    fields_config_id, profile_config_id, aggregation_config_id,
    is_active, weight
) VALUES (
    'lc_extraction', 'v1.0.0', 'letter_of_credit', '信用证解析默认模板',
    1, 2, 3,  -- 分别指向 config_versions 表的 ID
    TRUE, 100
);
```

### 权重分流

当同一 `template_id` 下有多个激活版本时，系统按权重随机选择：

```sql
-- 示例：A/B 测试配置
-- v1.0.0 权重 80%，v2.0.0 权重 20%
INSERT INTO config_templates (...) VALUES ('lc_extraction', 'v1.0.0', ..., TRUE, 80);
INSERT INTO config_templates (...) VALUES ('lc_extraction', 'v2.0.0', ..., TRUE, 20);
```

### 聚合策略

| 策略 | 说明 |
|------|------|
| `first_non_null` | 按页码顺序取第一个非空值 |
| `last_non_null` | 按页码顺序取最后一个非空值 |
| `max_confidence` | 取置信度最高的值 |
| `merge_lists` | 合并所有页的列表 |

### 决策追踪

每次请求的分流决策过程会记录在 `requests.trace` 字段中：

```json
{
  "doc_type": "letter_of_credit",
  "resolved_template_id": "lc_extraction",
  "candidates": [
    {"version": "v1.0.0", "weight": 80, "id": 1},
    {"version": "v2.0.0", "weight": 20, "id": 2}
  ],
  "total_weight": 100,
  "random_value": 65,
  "selected_index": 0,
  "selected_version": "v1.0.0",
  "warning": null
}
```

## 配置管理工具

使用 Streamlit 提供可视化的配置管理界面：

```bash
# 启动配置管理工具
cd develop/script/streamlit
streamlit run config_ui.py
```

### 功能模块

1. **配置版本管理**
   - 查看、新增、删除配置版本
   - 支持 fields、profile、aggregation 三种类型

2. **模板管理**
   - 查看所有模板（按 template_id 分组）
   - 新增模板：选择三个配置版本组合
   - 编辑模板：修改权重、激活状态、描述
   - 权重校验：显示同一 template_id 下权重总和

## 开发说明

### 模块依赖关系

```
main_api.py
├── image_preprocess.py
├── minio_upload.py
├── config_loader.py  ← 模板化配置加载
│   └── (config_versions, config_templates 表)
├── page_processor.py
│   └── field_extractor.py
│       └── vlm_client.py
├── aggregator.py
├── db_writer.py  ← 记录模板信息和分流决策
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

4. **配置加载失败**
   - 检查 `config_templates` 表是否有对应 doc_type 的激活模板
   - 检查 `config_versions` 表中对应的配置 ID 是否存在
   - 使用配置管理工具检查权重配置是否正确

5. **权重分流不符合预期**
   - 检查权重总和是否为 100
   - 查看 `requests.trace` 字段了解分流决策过程

## 版本历史

### v2.0.0
- 配置模板化：通过 config_templates 表管理配置组合
- 权重分流：支持按权重随机选择模板版本
- 决策追踪：记录详细的分流决策过程
- 移除 config_versions 表的 is_active 字段

### v1.0.0
- 基础功能：多页文档处理、字段提取、跨页聚合
- 配置版本化：支持配置版本管理

## License

MIT License
