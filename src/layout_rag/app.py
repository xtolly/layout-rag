import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from layout_rag.config import STATIC_DIR

from layout_rag.api.agent_endpoints import agent_router
from layout_rag.api.endpoints import router as api_router
from layout_rag.domain import NewDistributionBoxDomain
from layout_rag.services.layout_service import LayoutService

# --- 业务领域初始化 ---
# 如需切换到其他业务，只需替换此处的 domain 实例，其余代码不变。
domain = NewDistributionBoxDomain()

# --- 应用初始化 ---
app = FastAPI(title="智能元件布局系统 API")

# 将业务服务实例挂载到 app.state 中，以便 API 端点可以通过 Request 访问单例
app.state.layout_service = LayoutService(domain)

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

# --- 根路由 → 选配系统首页 ---
@app.get("/")
async def get_configurator():
    return FileResponse(STATIC_DIR / "configurator.html")

# --- 布局排版系统 ---
@app.get("/layout")
async def get_layout():
    return FileResponse(STATIC_DIR / "layout_workbench.html")

# --- 动态 UI 元数据接口 ---
@app.get("/api/ui-metadata")
async def get_ui_metadata():
    """获取当前业务的 UI 元数据（动态生成前端表单和列）"""
    return domain.ui_schema()

# --- API 路由挂载 ---
app.include_router(api_router, prefix="/api")
app.include_router(agent_router, prefix="/api")


if __name__ == "__main__":
    # 服务将运行在 http://localhost:8000
    uvicorn.run(app, host="0.0.0.0", port=8000)