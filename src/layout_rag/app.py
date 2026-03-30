import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from layout_rag.api.endpoints import router as api_router
from layout_rag.config import DATA_DIR, STATIC_DIR, VECTOR_STORE_PATH
from layout_rag.services.layout_service import LayoutService

# --- 应用初始化 ---
app = FastAPI(title="智能元件布局系统 API")

# 将业务服务实例挂载到 app.state 中，以便 API 端点可以通过 Request 访问单例
app.state.layout_service = LayoutService(DATA_DIR, VECTOR_STORE_PATH)

# --- 静态资源配置 ---
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

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
    return FileResponse(STATIC_DIR / "index.html")

# --- API 路由挂载 ---
app.include_router(api_router, prefix="/api")

if __name__ == "__main__":
    # 服务将运行在 http://localhost:8000
    uvicorn.run(app, host="0.0.0.0", port=8000)