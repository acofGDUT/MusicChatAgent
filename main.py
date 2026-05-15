# main.py
import logging
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware


# 导入你自己写的模块

from app.api.v1.endpoints import router as api_v1_router


# --- 1. 强制日志配置 ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    force=True,
)
logger = logging.getLogger("app.main")


app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"] ,
    allow_headers=["*"],
)
# --- 4. 挂载路由 ---
app.include_router(api_v1_router, prefix="/api/v1")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)