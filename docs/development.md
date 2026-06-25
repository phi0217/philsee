# 开发指南

本文档说明如何搭建 Philsee 的本地开发环境。

## 环境要求

- Python 3.11+
- MySQL 8.0+
- MinIO (或兼容 S3 的存储)
- VLM API (如 Qwen-VL)

## 快速开始

### 1. 克隆项目

```bash
git clone <repository-url>
cd philsee
```

### 2. 创建虚拟环境

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/macOS
# .venv\Scripts\activate  # Windows
```

### 3. 安装依赖

```bash
pip install -r requirements.txt
```

### 4. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env 文件，填写真实的连接信息
```

**环境变量说明**：

| 变量 | 必填 | 说明 |
|------|------|------|
| `VLM_ENDPOINT` | 是 | VLM 接口地址 |
| `VLM_MODEL` | 是 | 模型名称 |
| `VLM_API_KEY` | 是 | API 密钥 |
| `MINIO_ENDPOINT` | 是 | MinIO 地址 |
| `MINIO_ACCESS_KEY` | 是 | MinIO 用户 |
| `MINIO_SECRET_KEY` | 是 | MinIO 密码 |
| `MINIO_BUCKET` | 是 | 存储桶名称 |
| `MYSQL_HOST` | 是 | MySQL 主机 |
| `MYSQL_PORT` | 否 | MySQL 端口（默认 3306） |
| `MYSQL_USER` | 是 | MySQL 用户 |
| `MYSQL_PASSWORD` | 是 | MySQL 密码 |
| `MYSQL_DATABASE` | 是 | 数据库名称 |

### 5. 启动外部服务

**MySQL**:

```bash
docker run -d \
  --name philsee-mysql \
  -e MYSQL_ROOT_PASSWORD=password \
  -e MYSQL_DATABASE=philsee \
  -p 3306:3306 \
  mysql:8.0 \
  --character-set-server=utf8mb4 \
  --collation-server=utf8mb4_unicode_ci
```

**MinIO**:

```bash
docker run -d \
  --name philsee-minio \
  -e MINIO_ROOT_USER=admin \
  -e MINIO_ROOT_PASSWORD=admin123456 \
  -p 9000:9000 \
  -p 9001:9001 \
  minio/minio server /data --console-address ":9001"
```

### 6. 初始化数据库

```bash
mysql -h localhost -u root -p < sql/init_db.sql
```

### 7. 启动服务

```bash
# 开发模式（带热重载）
uvicorn online.main:app --reload --port 8000

# 或直接运行
python -m online.main
```

访问 http://localhost:8000/docs 查看 API 文档。

## 项目结构

```
philsee/
├── online/                     # 主代码包（分层架构）
│   ├── api/                    # API 层
│   ├── services/               # 服务层
│   ├── models/                 # 数据库模型
│   ├── schemas/                # Pydantic 模型
│   ├── repositories/           # 数据访问层
│   ├── processors/             # 处理器
│   ├── core/                   # 核心组件
│   ├── utils/                  # 工具函数
│   └── main.py                 # FastAPI 入口
├── config/                     # 配置管理
├── sql/                        # 数据库脚本
├── develop/                    # 开发辅助
├── tests/                      # 测试目录
└── docs/                       # 文档
```

详细说明见 [architecture.md](architecture.md)。

## 开发规范

### 分层架构

| 层级 | 目录 | 职责 |
|------|------|------|
| API | `api/routers/` | 路由、参数校验、响应 |
| Services | `services/` | 业务逻辑 |
| Repositories | `repositories/` | 数据库操作 |
| Processors | `processors/` | 文档处理管道 |
| Models | `models/` | ORM 模型 |
| Schemas | `schemas/` | Pydantic 模型 |

### 依赖方向

```
API → Services → Repositories → Models
            ↘ Processors
            ↘ Core
```

**禁止逆向依赖**。

### 新增功能检查清单

- [ ] 路由放在 `api/routers/`
- [ ] 业务逻辑放在 `services/`
- [ ] 数据库操作放在 `repositories/`
- [ ] 新表需要 `models/` 和 `schemas/`
- [ ] 配置项通过 `config/settings.py` 管理

## 运行测试

```bash
# 运行所有测试
pytest tests/

# 运行特定测试
pytest tests/unit/test_config_loader.py

# 带覆盖率报告
pytest --cov=online tests/
```

## 类型检查

```bash
mypy online/
```

## 代码格式化

```bash
# 格式化代码
black online/

# 排序导入
isort online/
```

## 常见问题

### 数据库连接失败

1. 检查 MySQL 是否启动
2. 确认 `.env` 中的数据库配置正确
3. 确认数据库已创建

### MinIO 上传失败

1. 检查 MinIO 是否启动
2. 确认 bucket 是否存在或有权创建

### VLM 调用失败

1. 检查 `VLM_ENDPOINT` 是否正确
2. 确认 API Key 有效
3. 检查网络连接

### 配置加载失败

1. 检查 `config_templates` 表是否有对应 doc_type 的激活模板
2. 检查 `config_versions` 表中对应的配置 ID 是否存在
3. 使用 Streamlit 工具检查权重配置

## 相关文档

- [系统架构](architecture.md)
- [API 参考](api-reference.md)
- [配置指南](configuration.md)
