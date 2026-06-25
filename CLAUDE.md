# Philsee 项目规则手册

> 本文档是 AI 协作开发的规则手册，记录项目约定、红线、命令速查。
> 历史变更请查看 git log，详细架构请查看 `docs/` 目录。

## 项目概览

智能单据解析服务：多页图片 → VLM 提取 → 跨页聚合 → 结果存储。

**技术栈**: FastAPI + SQLAlchemy (async) + MySQL + MinIO + VLM

## 环境变量速查

| 变量 | 说明 | 示例 |
|------|------|------|
| `VLM_ENDPOINT` | VLM 接口地址 | `http://gateway/v1/chat/completions` |
| `VLM_MODEL` | 模型名称 | `qwen-vl-max` |
| `VLM_API_KEY` | API 密钥 | - |
| `MINIO_ENDPOINT` | MinIO 地址 | `localhost:9000` |
| `MINIO_ACCESS_KEY` | MinIO 用户 | `admin` |
| `MINIO_SECRET_KEY` | MinIO 密码 | - |
| `MINIO_BUCKET` | 存储桶 | `philsee-images` |
| `MYSQL_HOST/PORT/USER/PASSWORD/DATABASE` | MySQL 连接 | - |

完整配置见 `config/settings.py`。

## 分层架构红线

### 目录职责

| 目录 | 职责 | 禁止 |
|------|------|------|
| `api/routers/` | 路由、参数校验、响应 | ❌ 业务逻辑 |
| `services/` | 业务逻辑、事务边界 | ❌ 直接 SQL |
| `repositories/` | 数据库操作 | ❌ 业务逻辑 |
| `processors/` | 文档处理管道 | ❌ 数据库操作 |
| `models/` | ORM 模型定义 | ❌ 业务方法 |
| `schemas/` | Pydantic 模型 | ❌ ORM 模型 |

### 模块依赖方向

```
API → Services → Repositories → Models
            ↘ Processors
            ↘ Core
```

**禁止逆向依赖**：Processors 不能直接调用 Repositories，必须通过 Services 传递数据。

### 新增功能检查清单

- [ ] 路由放在 `api/routers/`
- [ ] 业务逻辑放在 `services/`
- [ ] 数据库操作放在 `repositories/`
- [ ] 新表需要 `models/` 和对应的 `schemas/`
- [ ] 配置项通过 `config/settings.py` 管理

## 关键命令

```bash
# 启动服务（开发模式）
uvicorn online.main:app --reload --port 8000

# 初始化数据库
mysql -u root -p < sql/init_db.sql

# 运行测试
pytest tests/

# 类型检查
mypy online/
```

## 核心数据流

```
POST /parse
  ↓
extraction.py (路由)
  ↓
ExtractionService
  ├── ConfigService.load_config() → fields, profile, aggregation
  ├── Pipeline.process()
  │     ├── ImagePreprocess
  │     ├── PageProcessor → FieldExtractor → VLMClient
  │     └── Aggregator
  └── DBService.save_results()
```

## 配置模板机制

- **config_versions**: 存储三种配置（fields/profile/aggregation）的历史版本
- **config_templates**: 组合三个配置版本，支持权重分流
- **权重分流**: 同一 template_id 下多个版本按 weight 随机选择
- **决策追踪**: requests.trace 字段记录分流决策过程

## 数据库表速查

| 表 | 说明 |
|------|------|
| `config_versions` | 配置版本（fields/profile/aggregation） |
| `config_templates` | 配置模板（组合三个配置版本） |
| `requests` | 请求主表（含 trace） |
| `field_extractions` | 字段提取明细 |
| `agg_decisions` | 聚合决策记录 |

## 深入文档

- [架构设计](docs/architecture.md) - 系统架构详细说明
- [API 参考](docs/api-reference.md) - 接口文档
- [配置指南](docs/configuration.md) - 配置模板详解
- [开发指南](docs/development.md) - 本地开发环境搭建

## 禁止事项

- ❌ 不要在代码中硬编码 VLM 默认值（必须从环境变量读取）
- ❌ 不要修改 `develop/prompt/` 下的文件（历史记录，仅供参考）
- ❌ 不要在 Services 外直接操作数据库
- ❌ 不要在 Processors 中引入数据库依赖
- ❌ 不要跳过 `config/settings.py` 直接读取环境变量
