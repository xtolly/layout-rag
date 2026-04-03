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

@router.post("/cabinet-layout")
async def cabinet_layout(payload: Dict[str, Any] = Body(...)):
    """
    接口 4：柜体级别布局

    将柜体视为面板（画布），将各面板视为元件（可拖拽块），
    返回单条工作台数据供手动布局使用。
    若 payload 中不含 arrange，则调用 CabinetLayoutOptimizer 计算初始布局。

    输入 payload: { cabinet_id, cabinet_name, cabinet_use, cabinet_width, cabinet_height, ..., panels: [...] }
    返回: { name, uuid, layout_mode, scheme: { panel_id(=cabinet_id), panel_size, parts }, arrange }
    """
    import uuid as _uuid
    from layout_rag.core.cabinet_layout_optimizer import compute_cabinet_arrange

    panels = payload.get("panels", [])
    cabinet_width  = float(payload.get("cabinet_width")  or 800)
    cabinet_height = float(payload.get("cabinet_height") or 2200)

    # 每个面板作为一个元件
    parts = [
        {
            "part_id":    p.get("panel_id", str(_uuid.uuid4())),
            "part_type":  p.get("panel_type", ""),
            "part_model": p.get("operation_method", ""),
            "part_size":  [float(p.get("panel_width") or 600), float(p.get("panel_height") or 1400)],
        }
        for p in panels
    ]

    # 已有 arrange 则直接使用，否则计算初始布局
    existing_arrange = payload.get("arrange") or {}
    if not existing_arrange and parts:
        existing_arrange = compute_cabinet_arrange(cabinet_width, cabinet_height, parts)

    result = {
        "name":        f"{payload.get('cabinet_use', '')}-{payload.get('cabinet_name', '')}-{int(cabinet_width)}x{int(cabinet_height)}",
        "uuid":        str(_uuid.uuid4()),
        "layout_mode": "手动布局",
        "scheme": {
            "cabinet_id":    payload.get("cabinet_id", ""),
            "cabinet_name":  payload.get("cabinet_name", ""),
            "cabinet_use":   payload.get("cabinet_use", ""),
            "cabinet_model": payload.get("cabinet_model", ""),
            "panel_type":    f"{payload.get('cabinet_use', '')}-{payload.get('cabinet_name', '')}",
            "panel_id":      payload.get("cabinet_id", ""),  # 前端据此匹配柜体回写 arrange
            "panel_size":    [cabinet_width, cabinet_height],
            "parts":         parts,
        },
        "arrange": existing_arrange,
    }

    return result

