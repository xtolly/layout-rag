import os
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from services.layout_service import LayoutService
from api.endpoints import router as api_router

# --- 应用初始化 ---
app = FastAPI(title="智能元件布局系统 API")

# --- 资源初始化 ---
DATA_DIR = "data/layouts"
VECTOR_DB_PATH = "output/vector_store.json"

# 将业务服务实例挂载到 app.state 中，以便 API 端点可以通过 Request 访问单例
app.state.layout_service = LayoutService(DATA_DIR, VECTOR_DB_PATH)

# --- 静态资源配置 ---
if not os.path.exists("static"):
    os.makedirs("static")
app.mount("/static", StaticFiles(directory="static"), name="static")

# --- 跨域配置 ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 根路由 (前端入口) ---
@app.get("/")
async def get_index():
    return FileResponse("static/index.html")

# --- API 路由挂载 ---
app.include_router(api_router, prefix="/api")

if __name__ == "__main__":
    # 服务将运行在 http://localhost:8000
    uvicorn.run(app, host="0.0.0.0", port=8000)