# main.py
import logging
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

# 导入你自己写的模块
from app.core.auth import setup_global_credential
import app.core.auth as auth_module
from app.api.v1.endpoints import router as api_v1_router

# 导入 qqmusic_api 的底层类库
from qqmusic_api import Session, set_session

# --- 1. 强制日志配置 ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    force=True,
)
logger = logging.getLogger("app.main")


# --- 2. 生命周期 ---
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 正在启动服务，加载系统级配置...")
    await setup_global_credential()

    yield
    logger.info("🛑 服务关闭，释放系统资源...")


app = FastAPI(lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"] ,
    allow_headers=["*"],
)


#--- 3. 核心：请求拦截与 Session 管理中间件 ---

@app.middleware("http")
async def qqmusic_session_middleware(request: Request, call_next):
    """
    负责解决 contextvars 隔离问题，并防止 httpx 连接泄漏
    """
    # 步骤 A：新建一个传入了全局凭证的 Session
    # 查看源码可知，Session 初始化时接受 credential 参数
    session = Session(credential=auth_module.GLOBAL_CREDENTIAL)

    # 步骤 B：使用库作者提供的 set_session，强行把这个 Session 绑定到当前请求的上下文
    set_session(session)

    try:
        # 步骤 C：执行实际的路由逻辑 (比如你的 UserService 或 SearchService)
        response = await call_next(request)
        return response
    finally:
        # 步骤 D：请求结束，必须安全关闭底层的 httpx.AsyncClient！
        # 否则大量的外部请求会耗尽机器的 TCP 连接数
        await session.aclose()


# --- 4. 挂载路由 ---
app.include_router(api_v1_router, prefix="/api/v1")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)