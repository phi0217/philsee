"""
Philsee 文档解析服务 - FastAPI 应用入口

整合所有模块，提供文档解析 API。
支持配置模板化、按权重分流、分流决策追踪。
"""

import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse

from online.core.database import init_database, close_database
from online.core.trace_manager import get_trace_manager
from online.api.routers import extraction, template_generator

# 加载 .env 文件
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - [%(filename)s:%(lineno)d] - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理"""
    logger.info("应用启动中...")

    # 初始化数据库连接
    try:
        await init_database()
        logger.info("数据库连接初始化完成")
    except Exception as e:
        logger.error(f"数据库连接初始化失败: {e}")
        raise

    logger.info("应用启动完成")

    yield

    # 关闭资源
    await close_database()
    logger.info("应用关闭完成")


# 创建 FastAPI 应用
app = FastAPI(
    title="Philsee Document Parser",
    version="2.1.0",
    description="智能单据解析服务 - 支持配置模板化与分流决策追踪",
    lifespan=lifespan,
)

# 注册路由
app.include_router(extraction.router)
app.include_router(template_generator.router)


@app.get("/health")
async def health_check():
    """健康检查端点"""
    trace_manager = get_trace_manager()
    return {"status": "healthy", "traces_count": trace_manager.count()}


@app.get("/state/{trace_id}")
async def get_trace_state(trace_id: str):
    """获取请求状态"""
    trace_manager = get_trace_manager()
    state = trace_manager.get_state(trace_id)
    if not state:
        raise HTTPException(status_code=404, detail="trace_id not found")
    return {"trace_id": trace_id, "state": state}


if __name__ == "__main__":
    import uvicorn

    port = int(os.getenv("PORT", "8000"))
    uvicorn.run("online.main:app", host="0.0.0.0", port=port, reload=True)
