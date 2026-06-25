# Philsee Agent架构重构设计

> **版本**: v1.0  
> **日期**: 2026-06-25  
> **状态**: 已批准  
> **策略**: 完全重构 (选项C)

---

## 一、背景与目标

### 1.1 背景
当前Philsee项目实现了基础的单次VLM调用流程，但缺少多模型协同、Agent编排、幻觉对抗等高级能力。基于DeepSeek对话中讨论的"推理-工具交织"策略，需要对项目进行完全重构。

### 1.2 目标
构建一个基于"VLM裁决专家 + 专用模型助手 + Agent编排"的多智能体协同系统，实现：

- **三阶段Agent工作流**: 自我识别 → 工具调用 → 反思优化
- **多模型协同**: VLM + 5个专用模型（表格解析、OCR增强、版面分析、印章检测、签名识别）
- **幻觉对抗**: "推理-工具交织"策略有效降低VLM幻觉率
- **质量控制**: 业务校验 + 置信度评估 + 人工复审通道

### 1.3 约束条件
- 所有LLM/OCR/专用模型通过外部API调用，项目不部署模型服务
- 技术栈不变: FastAPI + SQLAlchemy + MySQL + MinIO
- Agent框架: LangGraph
- 完全重构，无向后兼容要求，无数据迁移需求

---

## 二、整体架构

### 2.1 架构层级

```
┌─────────────────────────────────────────────────────────────────────┐
│                            API层（FastAPI）                           │
│  POST /api/v2/parse | POST /api/v2/parse/async | config/review      │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│                     Agent编排层（LangGraph）                         │
│  工作流引擎: preprocess → layout_analysis → vlm_self →              │
│              tool_decision → tool_executor → vlm_rethink →          │
│              quality_control                                         │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│                       工具层（全部API调用）                          │
│  table_parser → ocr_enhancer → layout_analyzer →                   │
│  seal_detector → signature_recognizer                               │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│                         基础处理层                                  │
│  图像预处理管道 + 版面分析                                          │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│                         质量控制层                                  │
│  结构化校验引擎 + 置信度评估器 + 人工复审通道                        │
└─────────────────────────────────────────────────────────────────────┘
                                    ↓
┌─────────────────────────────────────────────────────────────────────┐
│                         数据持久层                                  │
│  parsing_requests | parsing_results | evidence_chain | ...          │
└─────────────────────────────────────────────────────────────────────┘
```

### 2.2 核心数据流

```
输入单据图片
    ↓ 基础处理层（图像预处理 + 版面分析）
    ↓ Agent编排层启动LangGraph工作流
    ↓ 阶段1: VLM自我识别（初步提取所有字段）
    ↓ 阶段2: 工具调用（根据任务调度专用模型API）
    ↓ 阶段3: VLM反思优化（对比证据，生成最终答案）
    ↓ 质量控制层（业务逻辑校验 + 置信度评估）
    ↓ 人工复审通道（低置信度/异常字段）
    ↓ 输出结构化结果
```

---

## 三、API接口设计

### 3.1 核心解析接口

```
POST /api/v2/parse
Content-Type: multipart/form-data

请求参数:
  - images: List[UploadFile] (必填, 图片文件列表)
  - doc_type: string (可选, 如"letter_of_credit")
  - config_profile: string (可选, 配置模板名称, 如"lc_agent_extraction")
  - enable_debug: boolean (可选, 默认false)
  - confidence_threshold: float (可选, 默认0.7)

响应:
{
  "trace_id": "uuid",
  "status": "success|failed|needs_review",
  "result": {
    "document_type": "letter_of_credit",
    "fields": [
      {
        "name": "lc_number",
        "value": "LC2024001234",
        "confidence": 0.95,
        "source": "vlm_rethink",
        "location": {"x1": 100, "y1": 200, "x2": 300, "y2": 250},
        "evidence": [
          {"type": "vlm_self", "value": "LC2024001234", "confidence": 0.92},
          {"type": "ocr_enhancer", "value": "LC2024001234", "confidence": 0.98}
        ],
        "needs_human_review": false,
        "validation_violations": []
      }
    ],
    "aggregated_confidence": 0.93,
    "warnings": [],
    "processing_steps": [
      {"step": "image_preprocessing", "status": "completed", "elapsed": 0.5},
      {"step": "layout_analysis", "status": "completed", "elapsed": 1.2},
      {"step": "vlm_self_recognition", "status": "completed", "elapsed": 3.1},
      {"step": "table_parsing", "status": "completed", "elapsed": 2.3},
      {"step": "vlm_rethink_optimization", "status": "completed", "elapsed": 2.8}
    ]
  },
  "debug_info": {}  // 仅enable_debug=true
}
```

### 3.2 异步处理接口

```
POST /api/v2/parse/async
# 参数同上，立即返回 {"trace_id": "uuid", "status": "accepted"}

GET /api/v2/parse/status/{trace_id}
# 返回处理状态和结果

GET /api/v2/parse/stream/{trace_id}
# SSE流式返回处理进度
```

### 3.3 配置管理接口

```
POST   /api/v2/config/profiles       # 创建/更新配置模板
GET    /api/v2/config/profiles       # 获取所有配置模板
GET    /api/v2/config/profiles/{name} # 获取特定配置模板
DELETE /api/v2/config/profiles/{name} # 删除配置模板
```

---

## 四、Agent工作流设计（LangGraph）

### 4.1 AgentState定义

```python
class AgentState(TypedDict):
    # 输入
    image_bytes: bytes
    image_base64: str
    doc_type: str
    config_profile: dict

    # 处理结果
    layout_analysis: Optional[dict]
    vlm_preliminary: Optional[dict]
    tool_requirements: List[dict]
    tool_results: List[dict]
    vlm_rethink: Optional[dict]
    final_fields: List[dict]
    confidence_scores: dict
    warnings: List[str]
    processing_steps: List[dict]

    # 控制流
    current_step: str
    should_continue: bool
```

### 4.2 工作流节点

| 节点 | 功能 | 输入 | 输出 |
|------|------|------|------|
| `preprocess` | 图像预处理(缩放/去噪/倾斜矫正) | image_bytes | image_bytes, image_base64 |
| `layout_analysis` | 版面元素检测(表格/印章/签名区域) | image_bytes | layout_analysis |
| `vlm_self` | VLM初步识别，用<self>标签输出 | image_base64 + layout | vlm_preliminary |
| `tool_decision` | 根据版面分析和VLM结果决定工具调用 | layout + preliminary | tool_requirements |
| `tool_executor` | 并行调用所需专用模型API | image_bytes + requirements | tool_results |
| `vlm_rethink` | VLM反思优化，综合证据输出<rethink>+<answer> | image_base64 + 全部证据 | vlm_rethink |
| `quality_control` | 业务校验+置信度评估+复审触发 | rethink结果 | final_fields + warnings |

### 4.3 工作流图

```
preprocess → layout_analysis → vlm_self → tool_decision
                                              ↓
                                    ┌─ 需要工具? ─┐
                                    ↓是           ↓否
                              tool_executor       │
                                    ↓              │
                                    └────→ vlm_rethink ←─┘
                                              ↓
                                       quality_control → END
```

### 4.4 三阶段"推理-工具交织"实现

**阶段1: 自我识别 `<self>`**
```python
prompt = f"""
版面分析: {layout_analysis}
字段定义: {config_profile['fields']}
请在<self>标签中输出初步识别结果。
"""
```

**阶段2: 工具调用 `<tool>`**
```python
# 并行调用所有所需工具
results = await asyncio.gather(*[
    tool.call(image_bytes, regions)
    for tool in required_tools
])
```

**阶段3: 反思优化 `<rethink>` + `<answer>`**
```python
prompt = f"""
你的初步结果: {vlm_preliminary}
工具调用结果: {tool_results}
请对比证据，在<rethink>中反思，在<answer>中输出最终JSON。
"""
```

---

## 五、工具层设计

### 5.1 统一接口

```python
class BaseModelTool:
    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config  # {endpoint, api_key, timeout, ...}

    async def call(self, image_bytes: bytes, regions: List[dict] = None) -> dict:
        """调用外部模型API，返回统一格式结果"""
        raise NotImplementedError
```

### 5.2 工具清单（按优先级）

| 优先级 | 工具名称 | 外部API | 功能 |
|--------|----------|---------|------|
| 1 | table_parser | PP-Structure API 或等效 | 表格结构解析(合并单元格等) |
| 2 | ocr_enhancer | PaddleOCR API 或等效 | 高精度文本识别 |
| 3 | layout_analyzer | LayoutLM API 或等效 | 版面元素检测与阅读顺序 |
| 4 | seal_detector | YOLOv11 API 或等效 | 印章定位与文字提取 |
| 5 | signature_recognizer | CrossViT API 或等效 | 手写签名识别 |

---

## 六、数据库设计

### 6.1 表结构

| 表名 | 说明 | 核心字段 |
|------|------|----------|
| `parsing_requests` | 解析请求主表 | trace_id, doc_type, status, needs_human_review |
| `parsing_results` | 字段解析结果 | field_name, field_value, confidence, source, location, evidence |
| `evidence_chain` | 证据链追踪 | step_type, model_name, input_data, output_data |
| `agent_config_profiles` | Agent配置模板 | workflow_config, vlm_config, tool_configs, fields |
| `model_invocations` | 模型调用统计 | model_name, input_tokens, processing_time_ms, success |
| `human_reviews` | 人工复审记录 | reviewer, review_action, original_value, reviewed_value |

### 6.2 表关系

```
parsing_requests (1) ──→ (N) parsing_results
parsing_requests (1) ──→ (N) evidence_chain
parsing_requests (1) ──→ (N) model_invocations
parsing_requests (1) ──→ (N) human_reviews
parsing_results  (1) ──→ (N) evidence_chain
parsing_results  (1) ──→ (N) human_reviews
agent_config_profiles (独立)
```

---

## 七、质量控制设计

### 7.1 ValidationEngine
- 类型校验: string/number/date/list
- 业务规则校验: 必填、格式、范围、正则
- 跨字段逻辑校验: 日期先后、金额币种一致性

### 7.2 ConfidenceAssessor
- 加权平均置信度: OCR > Table > VLM Rethink > VLM Self
- 证据一致性检查: 多源结果相似度计算
- 复审触发: confidence < 0.7 或 consistency < 0.5

### 7.3 HumanReviewManager
- 优先级排序: 关键字段 + 低置信度 + 验证违规
- 复审队列: 按优先级排队，支持分配审核人
- 结果回写: 更新parsing_results表

---

## 八、项目目录结构

```
philsee-v2/
├── api/                    # API层
│   ├── deps.py
│   ├── routers/            # parsing.py, config.py, review.py
│   └── middleware/         # trace.py, metrics.py, error_handler.py
├── agent/                  # Agent编排层
│   ├── graph.py            # LangGraph工作流构建
│   ├── state.py            # AgentState定义
│   ├── nodes/              # 7个工作流节点
│   └── edges/              # 条件边逻辑
├── tools/                  # 专用模型工具(全部API调用)
│   ├── base.py             # BaseModelTool
│   ├── registry.py         # 工具注册表
│   └── *.py                # 各工具实现
├── services/               # 业务逻辑层
│   ├── parsing_service.py
│   ├── config_service.py
│   └── review_service.py
├── core/                   # 核心组件
│   ├── vlm_client.py       # VLM API客户端
│   ├── database.py
│   ├── redis_client.py
│   ├── minio_client.py
│   └── settings.py
├── models/                 # SQLAlchemy ORM (6个表)
├── schemas/                # Pydantic模型
├── quality/                # 质量控制层
│   ├── validator.py
│   ├── confidence.py
│   └── review_manager.py
├── processors/             # 图像预处理
│   ├── pipeline.py
│   └── image_preprocess.py
├── utils/                  # 工具函数
├── config/                 # 配置文件
│   ├── profiles/           # 配置模板JSON
│   └── validation_rules/   # 校验规则JSON
├── sql/init.sql
├── tests/
├── docker-compose.yml      # 简化版(无模型服务)
└── Dockerfile
```

---

## 九、配置管理

### 9.1 配置模板结构

配置模板(agent_config_profiles表)包含以下部分：

- `workflow_config`: 启用的工作流节点、超时、调试开关
- `vlm_config`: self_recognition和rethink两个VLM调用的配置(endpoint/model/api_key/temperature)
- `tool_configs`: 5个工具的配置(endpoint/api_key/enabled/priority)
- `fields`: 字段定义(类型/描述/必填/校验规则)
- `quality_config`: 置信度阈值、自动复审触发规则

环境变量通过 `${VAR_NAME}` 格式引用，运行时解析。

### 9.2 配置加载

```python
# 从数据库加载配置模板
config = await config_service.load_profile("lc_agent_extraction")
# 自动解析 ${ENV_VAR} 占位符
config = resolve_env_vars(config)
```

---

## 十、评估体系

| 指标 | 目标值 | 说明 |
|------|--------|------|
| 字段级准确率 (Field Accuracy) | ≥ 0.95 | 所有提取字段中完全正确的比例 |
| 结构化编辑距离 (NED) | ≥ 0.90 | 提取文本与真实标签的接近程度 |
| 幻觉率 (Hallucination Rate) | ≤ 0.05 | VLM输出图片中不存在的字段比例 |
| 印章识别F1 | ≥ 0.90 | 印章检测与文字识别综合评分 |
| 签名识别准确率 | ≥ 0.95 | 手写签名识别准确率 |
| 人工复审率 | ≤ 0.05 | 需要人工介入的字段比例 |
| 工作流成功率 | ≥ 0.99 | Agent工作流完整执行比例 |

---

## 十一、部署架构

### 11.1 部署组件

```
Nginx LB → 3x API Server (FastAPI + LangGraph)
                ↓
         MySQL (数据持久化)
         Redis (缓存/会话)
         MinIO (图片存储)
         Prometheus + Grafana (监控)
                ↓
         [外部模型API - 不在本项目中]
```

### 11.2 Docker Compose服务清单

| 服务 | 镜像 | 副本数 |
|------|------|--------|
| api | philsee-v2:latest | 3 |
| mysql | mysql:8.0 | 1 |
| redis | redis:7-alpine | 1 |
| minio | minio/minio | 1 |
| prometheus | prom/prometheus | 1 |
| grafana | grafana/grafana | 1 |

### 11.3 关键环境变量

| 变量 | 说明 |
|------|------|
| `DATABASE_URL` | MySQL连接串 |
| `REDIS_URL` | Redis连接串 |
| `MINIO_*` | MinIO连接信息 |
| `VLM_SELF_ENDPOINT` | VLM自我识别API |
| `VLM_RETHINK_ENDPOINT` | VLM反思优化API |
| `TABLE_PARSER_API` | 表格解析API |
| `OCR_ENHANCER_API` | OCR增强API |
| `LAYOUT_ANALYZER_API` | 版面分析API |
| `SEAL_DETECTOR_API` | 印章检测API |
| `SIGNATURE_API` | 签名识别API |

---

## 十二、关键决策记录

| 决策 | 选项 | 理由 |
|------|------|------|
| 重构策略 | 完全重构 | 无历史数据, 追求最佳架构 |
| Agent框架 | LangGraph | 天然支持多Agent协作和条件分支 |
| 模型部署 | 全部外部API | 简化部署, 专注业务流程 |
| 技术栈 | 保持现有 | FastAPI + SQLAlchemy + MySQL + MinIO |
| 兼容性 | 不保持 | 无用户依赖, 完全重新设计 |