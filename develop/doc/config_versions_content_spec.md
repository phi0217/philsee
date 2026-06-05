# config_versions 表 content 字段规范文档

> **版本**: v2.1.0  
> **最后更新**: 2026-06-05  
> **适用项目**: philsee 通用文档解析系统

---

## 目录

1. [概述](#概述)
2. [通用说明](#通用说明)
3. [配置类型详解](#配置类型详解)
   - [config_type = 'fields'](#config_type--fields)
   - [config_type = 'profile'](#config_type--profile)
   - [config_type = 'aggregation'](#config_type--aggregation)
4. [处理管道](#处理管道)
   - [后处理管道（post_process）](#后处理管道post_process)
   - [前处理管道（pre_process）](#前处理管道pre_process)
   - [管道通用规则](#管道通用规则)
   - [自定义扩展函数](#自定义扩展函数)
5. [校验规则](#校验规则)
6. [完整示例](#完整示例)
7. [常见问题](#常见问题)

---

## 概述

`config_versions` 表是 philsee 系统的核心配置表，用于存储不同类型的配置版本。本文档详细说明 `content` 字段（JSON 格式）在不同 `config_type` 下的结构规范。

### 表结构概览

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `id` | INT | 主键 |
| `version_tag` | VARCHAR(64) | 版本标识，如 v1.0.0 |
| `doc_type` | VARCHAR(64) | 文档类型（fields 时为 `*`，其他为具体类型） |
| `config_type` | ENUM | 配置类型：`fields`, `profile`, `aggregation` |
| `content` | JSON | 配置内容（本文档核心） |
| `created_at` | TIMESTAMP | 创建时间 |
| `created_by` | VARCHAR(64) | 创建人 |
| `is_deleted` | BOOLEAN | 是否删除 |

---

## 通用说明

### config_type 取值

| 值 | 说明 | doc_type 取值 |
|----|------|--------------|
| `fields` | 全局字段定义 | 固定为 `*` |
| `profile` | 字段提取策略 | 具体文档类型，如 `invoice`, `letter_of_credit` |
| `aggregation` | 跨页聚合规则 | 具体文档类型，如 `invoice`, `letter_of_credit` |

### doc_type 说明

- **`*`（星号）**：表示全局定义，仅 `fields` 类型使用
- **具体类型**：如 `invoice`（发票）、`letter_of_credit`（信用证）等，用于 `profile` 和 `aggregation`

### 配置组合关系

```
config_templates (配置模板)
    ├── fields_config_id → config_versions (config_type='fields')
    ├── profile_config_id → config_versions (config_type='profile')
    ├── aggregation_config_id → config_versions (config_type='aggregation')
    └── pre_process → 前处理管道（模板级配置）
```

---

## 配置类型详解

### config_type = 'fields'

全局字段定义，定义系统中所有可用字段及其数据类型。

#### 顶层结构

```json
{
  "fields": {
    "<字段名>": <字段定义对象>,
    ...
  }
}
```

#### 字段定义对象属性

| 属性 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `type` | string | ✅ | 字段数据类型，可选值见下表 |
| `description` | string | ❌ | 字段描述，用于文档说明 |
| `item_schema` | object | ❌ | 当 `type="list"` 时，定义列表元素结构 |
| `properties` | object | ❌ | 当 `type="object"` 时，定义对象属性 |

#### type 可选值

| 值 | 说明 | 示例 |
|----|------|------|
| `string` | 字符串类型 | `"amount": {"type": "string"}` |
| `number` | 数值类型 | `"total": {"type": "number"}` |
| `list` | 列表/数组类型 | `"items": {"type": "list", "item_schema": {...}}` |
| `object` | 对象类型 | `"address": {"type": "object", "properties": {...}}` |

#### 嵌套结构说明

**item_schema（列表元素定义）**

当 `type="list"` 时，使用 `item_schema` 定义每个元素的结构：

```json
{
  "type": "list",
  "description": "货物清单",
  "item_schema": {
    "type": "object",
    "properties": {
      "hs_code": { "type": "string", "description": "海关编码" },
      "quantity": { "type": "number", "description": "数量" },
      "unit_price": { "type": "number", "description": "单价" }
    }
  }
}
```

**properties（对象属性定义）**

当 `type="object"` 时，使用 `properties` 定义对象的属性结构：

```json
{
  "type": "object",
  "description": "地址信息",
  "properties": {
    "country": { "type": "string", "description": "国家" },
    "city": { "type": "string", "description": "城市" },
    "street": { "type": "string", "description": "街道" }
  }
}
```

#### 完整示例

```json
{
  "fields": {
    "amount": {
      "type": "number",
      "description": "总金额"
    },
    "currency": {
      "type": "string",
      "description": "币种代码，如 USD、CNY"
    },
    "date": {
      "type": "string",
      "description": "日期"
    },
    "party": {
      "type": "string",
      "description": "当事人名称"
    },
    "lc_number": {
      "type": "string",
      "description": "信用证编号"
    },
    "commodities": {
      "type": "list",
      "description": "商品列表",
      "item_schema": {
        "type": "object",
        "properties": {
          "hs_code": { "type": "string", "description": "海关编码" },
          "quantity": { "type": "number", "description": "数量" },
          "unit_price": { "type": "number", "description": "单价" }
        }
      }
    }
  }
}
```

---

### config_type = 'profile'

字段提取策略，定义如何从文档中提取各字段。

#### 顶层结构

```json
{
  "fields": {
    "<字段名>": <字段策略对象>,
    ...
  }
}
```

> **注意**：在 v2.0 版本中，`doc_type` 字段已从 content 中移除，改为使用表的 `doc_type` 列。

#### 字段策略对象属性

| 属性 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `pages` | string \| array | ✅ | 指定该字段出现在哪些页 |
| `prompt_hint` | string | ✅ | VLM 提取提示词 |
| `post_process` | string | ❌ | 后处理管道（详见[处理管道](#处理管道)章节） |

#### pages 取值说明

| 类型 | 取值 | 说明 |
|------|------|------|
| 字符串 | `"all"` | 所有页都提取 |
| 字符串 | `"first"` | 仅第一页 |
| 字符串 | `"last"` | 仅最后一页 |
| 数组 | `[1, 2, 3]` | 指定页码列表 |
| 数组 | `[1]` | 单页（如第1页） |

#### 完整示例

```json
{
  "fields": {
    "lc_number": {
      "pages": "first",
      "prompt_hint": "请提取信用证编号，通常以 LC 开头，仅输出编号"
    },
    "amount": {
      "pages": "all",
      "prompt_hint": "请提取金额数值，仅输出数字，不含货币符号",
      "post_process": "strip|to_number|round(2)"
    },
    "currency": {
      "pages": "first",
      "prompt_hint": "请提取币种代码，如 USD、CNY、EUR 等",
      "post_process": "upper"
    },
    "date": {
      "pages": "first",
      "prompt_hint": "请提取日期，格式为 YYYY-MM-DD"
    },
    "party": {
      "pages": "all",
      "prompt_hint": "请提取申请人或受益人名称",
      "post_process": "strip"
    },
    "commodities": {
      "pages": "all",
      "prompt_hint": "请提取商品列表，返回 JSON 数组格式",
      "post_process": "strip|json_parse"
    }
  }
}
```

---

### config_type = 'aggregation'

跨页聚合规则，定义如何合并多页提取结果。

#### 顶层结构

```json
{
  "default": <默认聚合策略对象>,
  "<字段名>": <字段聚合策略对象>,
  ...
}
```

#### 聚合策略对象属性

| 属性 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `strategy` | string | ✅ | 聚合策略名称 |

#### strategy 可选值

| 值 | 说明 | 适用场景 |
|----|------|---------|
| `first_non_null` | 按页码顺序取第一个非空值 | 通常出现在文档开头的字段 |
| `last_non_null` | 按页码顺序取最后一个非空值 | 通常出现在文档结尾的字段 |
| `max_confidence` | 取置信度最高的值 | 需要高准确性的关键字段 |
| `merge_lists` | 按页码顺序合并所有列表 | 分布在多页的列表数据 |

#### 策略详解

##### first_non_null

```
页码:  1     2     3
值:   null  "A"   "B"
结果: "A" (取第一个非空的第2页)
```

##### last_non_null

```
页码:  1     2     3
值:   "A"   "B"   null
结果: "B" (取最后一个非空的第2页)
```

##### max_confidence

```
页码:      1          2          3
值:       "A"        "B"        "C"
置信度:   0.85       0.95       0.80
结果: "B" (置信度最高的第2页)
```

##### merge_lists

```
页码:    1           2           3
值:    [a, b]      [c, d]      [e]
结果: [a, b, c, d, e] (按顺序合并)
```

#### 完整示例

```json
{
  "default": {
    "strategy": "first_non_null"
  },
  "amount": {
    "strategy": "max_confidence"
  },
  "party": {
    "strategy": "last_non_null"
  },
  "commodities": {
    "strategy": "merge_lists"
  },
  "lc_number": {
    "strategy": "first_non_null"
  }
}
```

---

## 处理管道

处理管道允许通过配置组合多个处理步骤，实现灵活的数据处理能力。

### 后处理管道（post_process）

后处理管道用于对 VLM 提取的字段值进行处理。在 `profile` 配置的 `post_process` 字段中定义。

#### 支持的后处理函数

| 函数名 | 说明 | 示例 |
|--------|------|------|
| `strip` | 去除字符串首尾空白 | `strip` |
| `lower` | 转小写 | `lower` |
| `upper` | 转大写 | `upper` |
| `to_number` | 转换为数字（整数或浮点数），失败保留原值 | `to_number` |
| `to_string` | 强制转为字符串 | `to_string` |
| `json_parse` | 尝试解析 JSON 字符串为 Python 对象 | `json_parse` |
| `round(N)` | 对数字四舍五入保留 N 位小数 | `round(2)` |
| `replace(old,new)` | 替换子串 | `replace( ,_)` |

#### 使用示例

```json
{
  "amount": {
    "pages": [1],
    "prompt_hint": "提取总金额",
    "post_process": "strip|to_number|round(2)"
  },
  "currency": {
    "pages": "first",
    "prompt_hint": "提取币种",
    "post_process": "upper"
  },
  "commodities": {
    "pages": "all",
    "prompt_hint": "提取货物清单 JSON",
    "post_process": "strip|json_parse"
  },
  "invoice_no": {
    "pages": "first",
    "prompt_hint": "提取发票号",
    "post_process": "strip|replace( ,-)"
  }
}
```

---

### 前处理管道（pre_process）

前处理管道用于对整页图片进行处理，在字段提取之前执行。在 `config_templates` 表的 `pre_process` 字段中定义。

#### config_templates 表新增字段

| 字段名 | 类型 | 说明 |
|--------|------|------|
| `pre_process` | VARCHAR(255) | 前处理管道，管道符分隔 |

#### 支持的前处理函数

| 函数名 | 说明 | 示例 |
|--------|------|------|
| `fix_orientation` | 根据 EXIF 信息自动旋转图片 | `fix_orientation` |
| `deskew` | 倾斜矫正（使用霍夫变换检测并矫正） | `deskew` |
| `denoise` | 去噪（使用非局部均值算法） | `denoise` |
| `scale(short_edge)` | 缩放图片短边到指定像素 | `scale(1024)` |
| `crop(x1,y1,x2,y2)` | 裁剪图片区域（支持百分比或像素） | `crop(0,0,0.5,1)` |
| `to_grayscale` | 转为灰度图 | `to_grayscale` |
| `enhance_contrast` | 增强对比度（使用 CLAHE） | `enhance_contrast` |

#### 使用示例

```sql
-- 在 config_templates 表中配置
INSERT INTO config_templates (..., pre_process, ...)
VALUES (..., 'fix_orientation|deskew|scale(1024)', ...);
```

```
# 管道执行顺序
原始图片 
  → fix_orientation (EXIF 方向矫正)
  → deskew (倾斜矫正)
  → scale(1024) (缩放)
  → 送入字段提取流程
```

---

### 管道通用规则

#### 1. 语法规则

- 使用管道符 `|` 分隔多个处理步骤
- 步骤按从左到右顺序依次执行
- 每个步骤是一个函数名，可带参数
- 参数写在括号内，多个参数用逗号分隔
- **参数中不应包含管道符 `|`**

#### 2. 语法格式

```
func1|func2|func3(arg1)|func4(arg1,arg2)
```

#### 3. 执行规则

- 如果某个步骤执行失败，系统会记录错误日志并抛出异常
- 空管道（空字符串或空白）会被跳过，不影响原值
- 参数解析失败会导致该步骤执行失败

#### 4. 示例解析

| 管道字符串 | 解析结果 |
|-----------|---------|
| `strip` | `[("strip", [])]` |
| `strip\|to_number` | `[("strip", []), ("to_number", [])]` |
| `strip\|to_number\|round(2)` | `[("strip", []), ("to_number", []), ("round", ["2"])]` |
| `replace( ,_)` | `[("replace", [" ", "_"])]` |
| `crop(0,0,0.5,1)` | `[("crop", ["0", "0", "0.5", "1"])]` |

---

### 自定义扩展函数

系统支持注册自定义处理函数，实现特定业务需求。

#### 注册后处理函数

```python
from online.pipeline import register_post_processor

def custom_format(value, prefix="", suffix=""):
    """自定义格式化函数"""
    return f"{prefix}{value}{suffix}"

# 注册函数
register_post_processor("custom_format", custom_format)

# 使用：post_process = "strip|custom_format([,])"
# 结果："[原始值]"
```

#### 注册前处理函数

```python
from online.pipeline import register_pre_processor
import cv2
import numpy as np

def custom_filter(image, kernel_size="3"):
    """自定义图像滤波"""
    k = int(kernel_size)
    return cv2.GaussianBlur(image, (k, k), 0)

# 注册函数
register_pre_processor("custom_filter", custom_filter)

# 使用：pre_process = "fix_orientation|custom_filter(5)"
```

#### 函数签名要求

**后处理函数**：
```python
def post_func(value: Any, *args: str) -> Any:
    """
    Args:
        value: 当前值（已处理过的值）
        *args: 管道参数（字符串格式）
    Returns:
        处理后的值
    """
```

**前处理函数**：
```python
def pre_func(image: np.ndarray, *args: str) -> np.ndarray:
    """
    Args:
        image: OpenCV 图像数组 (BGR 格式)
        *args: 管道参数（字符串格式）
    Returns:
        处理后的图像数组
    """
```

---

## 校验规则

### 通用校验

| 规则 | 说明 |
|------|------|
| `content` 必须是有效的 JSON | 数据库层面通过 `JSON` 类型保证 |
| `version_tag` + `doc_type` + `config_type` 唯一 | 数据库唯一索引保证 |

### fields 类型校验

| 规则 | 错误级别 |
|------|----------|
| 顶层必须包含 `fields` 对象 | ❌ 错误 |
| `fields` 不能为空对象 | ⚠️ 警告 |
| 每个字段必须包含 `type` 属性 | ❌ 错误 |
| `type` 必须是 `string`/`number`/`list`/`object` 之一 | ❌ 错误 |
| `type="list"` 时必须包含 `item_schema` | ⚠️ 警告 |
| `type="object"` 时必须包含 `properties` | ⚠️ 警告 |

### profile 类型校验

| 规则 | 错误级别 |
|------|----------|
| 顶层必须包含 `fields` 对象 | ❌ 错误 |
| `fields` 不能为空对象 | ❌ 错误 |
| 每个字段策略必须包含 `pages` | ❌ 错误 |
| 每个字段策略必须包含 `prompt_hint` | ❌ 错误 |
| `pages` 数组中的页码必须 >= 1 | ❌ 错误 |
| `pages` 数组不能为空 | ❌ 错误 |
| `post_process` 必须是有效的管道格式 | ⚠️ 警告 |

### aggregation 类型校验

| 规则 | 错误级别 |
|------|----------|
| 至少包含 `default` 策略 | ⚠️ 建议 |
| `strategy` 必须是有效值 | ❌ 错误 |
| 建议为所有 fields 中定义的字段指定策略 | ⚠️ 建议 |

---

## 完整示例

以下示例展示了发票（invoice）文档的完整配置组合，包含处理管道的使用。

### 1. fields 配置 (doc_type = '*')

```json
{
  "fields": {
    "amount": {
      "type": "number",
      "description": "金额"
    },
    "currency": {
      "type": "string",
      "description": "币种"
    },
    "date": {
      "type": "string",
      "description": "日期"
    },
    "party": {
      "type": "string",
      "description": "当事人"
    },
    "invoice_no": {
      "type": "string",
      "description": "发票号"
    },
    "commodities": {
      "type": "list",
      "description": "商品列表"
    }
  }
}
```

### 2. profile 配置 (doc_type = 'invoice')

```json
{
  "fields": {
    "invoice_no": {
      "prompt_hint": "请提取发票号",
      "pages": "first",
      "post_process": "strip|upper|replace( ,)"
    },
    "amount": {
      "prompt_hint": "请提取金额数值",
      "pages": "all",
      "post_process": "strip|to_number|round(2)"
    },
    "currency": {
      "prompt_hint": "请提取币种代码，如 USD、CNY",
      "pages": "first",
      "post_process": "strip|upper"
    },
    "date": {
      "prompt_hint": "请提取日期，格式为 YYYY-MM-DD",
      "pages": "first",
      "post_process": "strip"
    },
    "party": {
      "prompt_hint": "请提取开票方或收票方名称",
      "pages": "first",
      "post_process": "strip"
    },
    "commodities": {
      "prompt_hint": "请提取商品列表，返回 JSON 数组格式",
      "pages": "all",
      "post_process": "strip|json_parse"
    }
  }
}
```

### 3. aggregation 配置 (doc_type = 'invoice')

```json
{
  "default": {
    "strategy": "first_non_null"
  },
  "amount": {
    "strategy": "max_confidence"
  },
  "commodities": {
    "strategy": "merge_lists"
  }
}
```

### 4. config_templates 记录

```sql
INSERT INTO config_templates (
    template_id, version, doc_type, description,
    fields_config_id, profile_config_id, aggregation_config_id,
    pre_process, is_active, weight, created_by
) VALUES (
    'invoice_extraction', 'v1.0.0', 'invoice', '发票解析默认模板',
    1, 5, 6,
    'fix_orientation|deskew|scale(1024)',
    TRUE, 100, 'system'
);
```

---

## 常见问题

### Q1: fields 配置中的字段与 profile 配置不匹配怎么办？

**A**: 系统会优先使用 profile 中定义的字段策略。如果 profile 中引用了 fields 中未定义的字段，系统会发出警告但不会报错。建议保持两者一致。

### Q2: 如果某个字段在 profile 中没有定义聚合策略怎么办？

**A**: 系统会使用 `default` 策略。如果未定义 `default`，则默认使用 `first_non_null`。

### Q3: pages 使用数组还是字符串？

**A**: 
- 单页：使用字符串 `"first"` 或 `"last"` 更简洁
- 多页：使用数组 `[1, 2, 3]`
- 全部页面：使用字符串 `"all"`

### Q4: 后处理管道执行顺序是什么？

**A**: 从左到右依次执行。例如 `strip|to_number|round(2)` 的执行顺序：
1. `strip`: 去除空白 → `" 123.45 "` → `"123.45"`
2. `to_number`: 转数字 → `123.45`
3. `round(2)`: 保留2位小数 → `123.45`

### Q5: 前处理管道在什么时候执行？

**A**: 前处理管道在图片预处理阶段执行，顺序为：
1. 读取原始图片
2. 执行 `pre_process` 管道（如 `fix_orientation|deskew`）
3. 执行标准预处理（缩放到目标尺寸）
4. 编码为 base64 送入 VLM

### Q6: 处理管道中某个步骤失败会怎样？

**A**: 
- 后处理管道：步骤失败会抛出异常，字段值保持为原始提取值
- 前处理管道：步骤失败会记录警告并使用原图继续处理

### Q7: 如何添加自定义处理函数？

**A**: 使用 `register_post_processor` 或 `register_pre_processor` 函数注册自定义函数，详见[自定义扩展函数](#自定义扩展函数)章节。

### Q8: 版本如何管理？

**A**: 
- 每个配置版本都有唯一的 `version_tag`（如 v1.0.0）
- 修改配置时创建新版本，不覆盖旧版本
- 通过 `config_templates` 表指定使用哪个版本
- 支持按权重分流不同版本

---

## 附录

### 相关文件

| 文件 | 说明 |
|------|------|
| [sql/init_db.sql](../../sql/init_db.sql) | 数据库初始化脚本 |
| [online/config_loader.py](../../online/config_loader.py) | 配置加载模块 |
| [online/pipeline.py](../../online/pipeline.py) | 处理管道模块 |
| [online/aggregator.py](../../online/aggregator.py) | 聚合处理模块 |
| [develop/script/streamlit/config_ui.py](../script/streamlit/config_ui.py) | 配置管理界面 |

### 版本历史

| 版本 | 日期 | 变更说明 |
|------|------|----------|
| v2.1.0 | 2026-06-05 | 新增处理管道（post_process/pre_process）支持 |
| v2.0.0 | 2026-06-05 | 配置模板化，移除 content 中的 doc_type 字段 |
| v1.0.0 | - | 初始版本 |

---

> 📝 **文档维护**: 如有问题或建议，请联系项目维护人员。
