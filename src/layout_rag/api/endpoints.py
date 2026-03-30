from fastapi import APIRouter, Body, Request, Depends
from typing import Dict, Any

router = APIRouter()

# 辅助函数：从 app.state 中获取 service 实例
def get_service(request: Request):
    return request.app.state.layout_service

@router.get("/schema")
async def get_schema(service=Depends(get_service)):
    """返回当前系统的特征定义元数据"""
    return service.schema_def

@router.get("/part-color-map")
async def get_part_color_map(service=Depends(get_service)):
    """返回元件类型颜色映射及未知类型兜底颜色"""
    return service.get_part_color_map()

@router.post("/recommend")
async def recommend_layout(
    project_data: Dict[str, Any] = Body(...),
    service=Depends(get_service)
):
    """接口 1：执行基于相似特征的真实推荐检索"""
    templates = service.search_recommendations(project_data)
    return {"templates": templates}

@router.post("/apply")
async def apply_template(
    payload: Dict[str, Any] = Body(...),
    service=Depends(get_service)
):
    """接口 2：应用选中的模板，为原数据填充排版坐标 arrange"""
    template_uuid = payload.get("template_uuid")
    other_template_uuids = payload.get("other_template_uuids", [])
    project_data = payload.get("project_data", {})
    
    updated_data = service.apply_layout_template(template_uuid, project_data, other_template_uuids)
    return updated_data

@router.post("/submit")
async def submit_layout(project_data: Dict[str, Any] = Body(...)):
    """接口 3：接收最终的人工微调结果"""
    # 实际生产中这里应有持久化逻辑
    print("收到最终提交的布局数据，包含元件数:", len(project_data.get("meta", {}).get("parts", [])))
    return {"status": "success", "message": "布局数据保存成功"}
