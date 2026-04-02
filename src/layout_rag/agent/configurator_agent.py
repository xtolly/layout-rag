"""
配电柜选配智能体 — 基于 LangGraph ReAct 模式

工具集：
  - add_cabinet   添加箱柜（含面板和元件完整信息）
  - add_panel     添加面板到指定/当前箱柜
  - add_part      添加元件到指定/当前面板
  - edit_cabinet  修改已有箱柜属性
  - edit_panel    修改已有面板属性
  - edit_part     修改已有元件属性
  - get_current_selection 获取当前选中状态
  - get_scheme_summary    获取当前方案摘要
"""
from __future__ import annotations

import json
import os
import uuid as _uuid
from typing import Annotated, Optional

from langchain_core.messages import SystemMessage
from langchain_core.tools import tool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, Field
from typing_extensions import TypedDict


from dotenv import load_dotenv

load_dotenv()  # 解析项目根目录下的 .env 文件

# ──────────────────────────────────────────────────────────────
#  Qwen LLM
# ──────────────────────────────────────────────────────────────

def _make_openai_cls():
    """
    构造支持 reasoning_content 的 ChatOpenAI 子类。

    langchain-openai 的 ChatOpenAI 明确不提取非标准 delta 字段
    （如 Qwen / DeepSeek 的 reasoning_content），这里通过重写
    _convert_chunk_to_generation_chunk 把它注入 additional_kwargs，
    使下游 astream_events 能够拿到思考过程。
    """
    from langchain_openai import ChatOpenAI
    from langchain_core.messages import AIMessageChunk
    from langchain_core.outputs import ChatGenerationChunk

    class _ChatOpenAIReasoning(ChatOpenAI):  # type: ignore[misc]

        def _convert_chunk_to_generation_chunk(
            self, chunk, default_chunk_class, base_generation_info,
        ) -> ChatGenerationChunk | None:
            result = super()._convert_chunk_to_generation_chunk(
                chunk, default_chunk_class, base_generation_info,
            )
            if result is None:
                return None

            choices = (
                chunk.get("choices", [])
                or chunk.get("chunk", {}).get("choices", [])
            )
            if choices:
                delta = choices[0].get("delta") or {}
                reasoning = delta.get("reasoning_content")
                if reasoning and isinstance(result.message, AIMessageChunk):
                    result.message.additional_kwargs["reasoning_content"] = reasoning

            return result

    return _ChatOpenAIReasoning


def _build_llm():
    """构建 LLM，默认读取 .env 中的 OpenAI 兼容配置"""
    api_key = os.getenv("OPENAI_API_KEY", os.getenv("DASHSCOPE_API_KEY", ""))
    base_url = os.getenv("OPENAI_API_BASE", os.getenv("QWEN_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1"))
    model_name = os.getenv("MODEL_NAME", os.getenv("QWEN_MODEL", "qwen-plus"))

    # 方式 2：OpenAI 兼容接口（带 reasoning_content 支持）
    ChatOpenAIReasoning = _make_openai_cls()
    return ChatOpenAIReasoning(
        model=model_name,
        base_url=base_url,
        api_key=api_key or "sk-placeholder",
        temperature=0.3,
        streaming=True,
        extra_body={"enable_thinking": True},
    )


# ──────────────────────────────────────────────────────────────
#  Agent 状态
# ──────────────────────────────────────────────────────────────
class AgentState(TypedDict):
    messages: Annotated[list, add_messages]
    current_scheme: dict


# ──────────────────────────────────────────────────────────────
#  工具
# ──────────────────────────────────────────────────────────────

# ── 前端选中状态（由 API 层在每次请求前写入） ──
_current_selection: dict = {"cabinet_id": "", "panel_id": ""}
_current_scheme: dict = {"cabinets": []}


def set_current_selection(selection: dict) -> None:
    """由 API 层调用，每次请求前写入前端选中的箱柜/面板 ID"""
    global _current_selection
    _current_selection = selection or {"cabinet_id": "", "panel_id": ""}


def set_current_scheme(scheme: dict) -> None:
    """由 API 层调用，每次请求前写入前端当前方案"""
    global _current_scheme
    _current_scheme = scheme or {"cabinets": []}


def _uuid4() -> str:
    return str(_uuid.uuid4())


# ── 结构化输入 ──
class PartInput(BaseModel):
    order: int = Field(default=0, description="序号，用于前端排序，提取多项时请严格按顺序递增给出")
    part_type: str = Field(default="", description="元件标准名称，必须从标准名称列表中选取；无法识别时留空")
    part_model: str = Field(default="", description="元件型号规格，如 DW15-630；无法识别时留空")
    part_number: int = Field(default=1, description="数量")
    part_width: int = Field(default=80, description="元件宽度(mm)，根据元件类型推测合理值")
    part_height: int = Field(default=100, description="元件高度(mm)，根据元件类型推测合理值")


class PanelInput(BaseModel):
    order: int = Field(default=0, description="序号，用于前端排序，提取多项时请严格按顺序递增给出")
    panel_type: str = Field(default="默认面板", description="默认面板 / 抽屉面板")
    operation_method: str = Field(default="", description="操作方式：手动机构/电动操作/抽屉式；无法识别时留空")
    panel_width: int = Field(default=800, description="面板宽度(mm)，未知时按柜体宽度推测")
    panel_height: int = Field(default=2200, description="面板高度(mm)，未知时按柜体高度推测")
    parts: list[PartInput] = Field(default_factory=list)


class CabinetInput(BaseModel):
    order: int = Field(default=0, description="序号，用于前端排序，提取多项时请严格按顺序递增给出")
    cabinet_name: str = Field(default="", description="柜名/柜编号：如 1AL")
    cabinet_use: str = Field(default="出线柜", description="柜用途：进线柜/出线柜/电容补偿柜/计量柜/联络柜；根据元件配置推测")
    cabinet_model: str = Field(default="GGD", description="柜型号：GCK/GCS/MNS/GGD；根据用途和面板类型推测")
    wiring_method: str = Field(default="", description="进出线方式：上进上出/上进下出/下进上出/下进下出；无法识别时留空")
    cabinet_width: int = Field(default=800, description="柜宽(mm)，未知时按柜型推测常见值")
    cabinet_height: int = Field(default=2200, description="柜高(mm)，未知时按柜型推测常见值")
    panels: list[PanelInput] = Field(default_factory=list)


class AddCabinetsInput(BaseModel):
    cabinets: list[CabinetInput] = Field(description="新添加的箱柜列表")

class AddPanelsInput(BaseModel):
    cabinet_id: str = Field(default="", description="目标箱柜 ID；留空则添加到当前选中的箱柜")
    panels: list[PanelInput] = Field(description="新添加的面板列表")

class AddPartsInput(BaseModel):
    panel_id: str = Field(default="", description="目标面板 ID；留空则添加到当前选中的面板")
    parts: list[PartInput] = Field(description="新添加的元件列表")


def _assign_ids_to_panel(panel_dict: dict) -> dict:
    """为面板及其元件自动分配 ID"""
    panel_dict["panel_id"] = _uuid4()
    for pt in panel_dict.get("parts", []):
        pt["part_id"] = _uuid4()
    return panel_dict


@tool(args_schema=AddCabinetsInput)
def add_cabinets(**kwargs) -> str:
    """批量添加箱柜（含面板和元件完整信息）。当用户描述新箱柜时调用，支持一次添加多个，并支持嵌套面板和元件。id 由系统自动生成。"""
    cabs_input = AddCabinetsInput(**kwargs).model_dump()
    cabs = cabs_input.get("cabinets", [])
    for cab in cabs:
        cab["cabinet_id"] = _uuid4()
        for p in cab.get("panels", []):
            _assign_ids_to_panel(p)

    parts_n = sum(len(p.get("parts", [])) for cab in cabs for p in cab.get("panels", []))
    msg = f"已批量添加 {len(cabs)} 个箱柜（共包含 {parts_n} 个初始元件）"
    return json.dumps(
        {
            "action": "add_cabinets",
            "cabinets": cabs,
            "message": msg,
        },
        ensure_ascii=False,
    )


@tool(args_schema=AddPanelsInput)
def add_panels(**kwargs) -> str:
    """批量添加多个面板（含元件完整信息）到指定箱柜。cabinet_id 留空则添加到当前选中的箱柜。"""
    input_data = AddPanelsInput(**kwargs)
    target_cab_id = input_data.cabinet_id or _current_selection.get("cabinet_id", "")
    if not target_cab_id:
        return json.dumps({"action": "error", "message": "未指定目标箱柜且当前未选中任何箱柜，请先选中一个箱柜"}, ensure_ascii=False)

    panels = input_data.model_dump(exclude={"cabinet_id"}).get("panels", [])
    for p in panels:
        _assign_ids_to_panel(p)

    return json.dumps(
        {
            "action": "add_panels",
            "cabinet_id": target_cab_id,
            "panels": panels,
            "message": f"已批量添加 {len(panels)} 个面板到箱柜 {target_cab_id}",
        },
        ensure_ascii=False,
    )


@tool(args_schema=AddPartsInput)
def add_parts(**kwargs) -> str:
    """批量添加多个元件到指定面板。panel_id 留空则添加到当前选中的面板。"""
    input_data = AddPartsInput(**kwargs)
    target_pan_id = input_data.panel_id or _current_selection.get("panel_id", "")
    if not target_pan_id:
        return json.dumps({"action": "error", "message": "未指定目标面板且当前未选中任何面板，请先选中一个面板"}, ensure_ascii=False)

    parts = input_data.model_dump(exclude={"panel_id"}).get("parts", [])
    for pt in parts:
        pt["part_id"] = _uuid4()

    return json.dumps(
        {
            "action": "add_parts",
            "panel_id": target_pan_id,
            "parts": parts,
            "message": f"已批量添加 {len(parts)} 个元件到面板 {target_pan_id}",
        },
        ensure_ascii=False,
    )


@tool
def edit_cabinet(
    cabinet_id: str,
    cabinet_name: Optional[str] = None,
    cabinet_use: Optional[str] = None,
    cabinet_model: Optional[str] = None,
    wiring_method: Optional[str] = None,
    cabinet_width: Optional[int] = None,
    cabinet_height: Optional[int] = None,
) -> str:
    """
    修改已有箱柜的属性（仅传需要修改的字段）。
    cabinet_id: 要修改的箱柜 ID（定位用，通过 get_current_selection 或 get_scheme_summary 获取）
    其余字段：需要修改的新值，不传则保持不变
    """
    updates: dict = {}
    if cabinet_name:  updates["cabinet_name"] = cabinet_name
    if cabinet_use:   updates["cabinet_use"] = cabinet_use
    if cabinet_model: updates["cabinet_model"] = cabinet_model
    if wiring_method: updates["wiring_method"] = wiring_method
    if cabinet_width:  updates["cabinet_width"] = cabinet_width
    if cabinet_height:  updates["cabinet_height"] = cabinet_height

    return json.dumps(
        {
            "action": "edit_cabinet",
            "cabinet_id": cabinet_id,
            "updates": updates,
            "message": f"已更新箱柜 {cabinet_id}：{updates}",
        },
        ensure_ascii=False,
    )


@tool
def edit_panel(
    panel_id: str,
    panel_type: Optional[str] = None,
    operation_method: Optional[str] = None,
    panel_width: Optional[int] = None,
    panel_height: Optional[int] = None,
) -> str:
    """
    修改已有面板的属性。
    panel_id: 要修改的面板 ID（通过 get_current_selection 或 get_scheme_summary 获取）
    """
    updates: dict = {}
    if panel_type:   updates["panel_type"] = panel_type
    if operation_method: updates["operation_method"] = operation_method
    if panel_width:  updates["panel_width"] = panel_width
    if panel_height: updates["panel_height"] = panel_height

    return json.dumps(
        {
            "action": "edit_panel",
            "panel_id": panel_id,
            "updates": updates,
            "message": f"已更新面板 {panel_id}：{updates}",
        },
        ensure_ascii=False,
    )


@tool
def edit_part(
    part_id: str,
    part_type: Optional[str] = None,
    part_model: Optional[str] = None,
    part_number: Optional[int] = None,
    part_width: Optional[int] = None,
    part_height: Optional[int] = None,
) -> str:
    """
    修改已有元件的属性。
    part_id: 要修改的元件 ID（定位用，通过 get_current_selection 或 get_scheme_summary 获取）
    """
    updates: dict = {}
    if part_type:   updates["part_type"] = part_type
    if part_model:  updates["part_model"] = part_model
    if part_number is not None: updates["part_number"] = part_number
    if part_width:  updates["part_width"] = part_width
    if part_height: updates["part_height"] = part_height

    return json.dumps(
        {
            "action": "edit_part",
            "part_id": part_id,
            "updates": updates,
            "message": f"已更新元件 {part_id}：{updates}",
        },
        ensure_ascii=False,
    )

@tool
def get_current_selection() -> str:
    """
    获取用户当前在界面上选中的箱柜和面板的完整信息（含 ID、名称、面板列表、元件列表）。
    当用户说"当前面板"/"当前箱柜"或要编辑某个元件时，先调用此工具获取目标 ID。
    """
    cab_id = _current_selection.get("cabinet_id", "")
    pan_id = _current_selection.get("panel_id", "")
    lines: list[str] = []

    # 在当前方案中查找选中的箱柜
    sel_cabinet = None
    for c in _current_scheme.get("cabinets", []):
        if c.get("cabinet_id") == cab_id:
            sel_cabinet = c
            break

    if sel_cabinet:
        lines.append(
            f"当前选中箱柜: [{cab_id}] {sel_cabinet.get('cabinet_name','?')}"
            f"（{sel_cabinet.get('cabinet_use','?')}，{sel_cabinet.get('cabinet_model','?')}）"
        )
        # 列出该箱柜的所有面板
        for pn in sel_cabinet.get("panels", []):
            pid = pn.get('panel_id', '?')
            marker = " ← 当前选中" if pid == pan_id else ""
            lines.append(f"  面板 [{pid}] {pn.get('panel_type','?')}{marker}")
            for pt in pn.get("parts", []):
                lines.append(
                    f"    元件 [{pt.get('part_id','?')}] {pt.get('part_type','?')} "
                    f"{pt.get('part_model','')} ×{pt.get('part_number',1)}"
                )
    else:
        lines.append("当前未选中任何箱柜" if not cab_id else f"选中的箱柜 ID {cab_id} 在方案中未找到")

    if not pan_id:
        lines.append("当前未选中任何面板")

    return "\n".join(lines)


@tool
def get_scheme_summary() -> str:
    """
    获取当前方案的统计摘要，帮助了解已有配置。无需传参，直接读取当前方案。
    """
    cabinets = _current_scheme.get("cabinets", [])
    if not cabinets:
        return "当前方案为空，尚未配置任何箱柜。"
    lines = [f"当前方案共 {len(cabinets)} 台箱柜："]
    for c in cabinets:
        panels = c.get("panels", [])
        parts_total = sum(
            sum(p.get("part_number", 1) for p in pn.get("parts", []))
            for pn in panels
        )
        cab_id = c.get('cabinet_id', '?')
        lines.append(
            f"  · [{cab_id}] {c.get('cabinet_name','?')}（{c.get('cabinet_use','?')}，"
            f"{c.get('cabinet_model','?')}）— {len(panels)} 个面板，{parts_total} 个元件"
        )
        for pn in panels:
            pan_id = pn.get('panel_id', '?')
            pn_parts = pn.get('parts', [])
            lines.append(
                f"      面板 [{pan_id}] {pn.get('panel_type','?')} — {len(pn_parts)} 种元件"
            )
            for pt in pn_parts:
                pt_id = pt.get('part_id', '?')
                lines.append(
                    f"        元件 [{pt_id}] {pt.get('part_type','?')} {pt.get('part_model','')} ×{pt.get('part_number',1)}"
                )
    return "\n".join(lines)


def _load_standard_names() -> list[str]:
    """从 standard_names.txt 加载元件标准名称列表"""
    import pathlib
    # __file__ = src/layout_rag/agent/configurator_agent.py
    # parents[3] = src/, parents[3]/../static = project_root/static
    base = pathlib.Path(__file__).resolve().parents[3]
    txt_path = base / "static" / "standard_names.txt"
    try:
        return [n.strip() for n in txt_path.read_text(encoding="utf-8").splitlines() if n.strip()]
    except Exception:
        return []


STANDARD_PART_NAMES = _load_standard_names()
_PART_NAMES_STR = "、".join(STANDARD_PART_NAMES) if STANDARD_PART_NAMES else "（未能加载标准名称）"


# ──────────────────────────────────────────────────────────────
#  系统提示词
# ──────────────────────────────────────────────────────────────
SYSTEM_PROMPT = f"""你是一个专业的配电柜选配助手，帮助用户设计低压配电系统方案。

【核心规则】
1. 当用户描述方案需求时，为每个箱柜调用 **add_cabinets**（传入完整的面板和元件），支持一次性创建多个箱柜。
2. 当用户想给已有箱柜新增面板时，调用 **add_panels**；新增多项元件时调用 **add_parts**。如果用户没指定目标箱柜/面板，工具会自动使用当前选中的。
3. 当用户想修改已有内容时，调用 edit_* 工具。**edit 工具统一使用 ID 定位**（cabinet_id / panel_id / part_id）。
4. 查找 ID 的方法：
   - 用户说"当前面板"/"当前箱柜"→ 调用 **get_current_selection**，返回选中箱柜及其所有面板和元件的 ID。
   - 用户用名称描述（如"修改1AL箱柜的断路器"）→ 调用 **get_scheme_summary** 查看完整方案，从中匹配名称找到对应 ID。
5. 每次工具调用后，向用户简要说明做了什么。

【未明确指定时的推测规则】
- **柜用途**：根据元件配置推测（如有主进线断路器→进线柜，多回路出线→出线柜，电容器→电容补偿柜）。
- **柜型号**：可为空。
- **柜体尺寸**：常见值 800×2200mm，抽屉柜常见 600/800×2200mm。
- **面板尺寸**：默认等于柜体尺寸；抽屉面板常见 600×200mm。
- **元件尺寸**：根据元件类型推测（断路器约 140×250，接触器约 80×120，熔断器约 60×80 等）。
- **元件名称 part_type**：必须从标准名称列表中选取；确实无法匹配时留空。
- **元件型号 part_model**：无法识别时留空。
- 推测的值在回复中用"（推测）"标注，提示用户确认或修改。

【排序规则】
- 为箱柜、面板、元件的 order 字段分配递增的数字索引（1,2,3...），确保在前端创建后保持正确的图纸阅读顺序！

【面板规则】
- **出线柜/抽屉柜中，一个出线回路就是一个独立的抽屉面板，n个回路就有 n个抽屉面板**。抽屉面板的高度计算：如果能识别出每个抽屉面板的模数，则高度 = 25mm × 模数；如果不能识别模数，则高度 = (柜体总高度 / 抽屉数量) 向下取整。
- **其他柜型通常只有一个"默认面板"**，面板尺寸与柜体尺寸一致，内部元件平铺安装在这个面板上。
- **面板尺寸不允许填 0**，如果无法识别面板尺寸，**必须使用该面板所属柜体的宽度和高度**。

【图片分析】
当用户发送了图片（如配电系统图、单线图、系统图、配电柜照片、元件清单表等），请：
1. 仔细识别图中信息：箱柜数量与类型、各回路配置、元件型号与规格参数、额定电流/电压等。
2. 对于出线柜，注意从图中识别回路数量，然后创建对应数量的抽屉面板。
3. 提取关键数据后，**为识别到的箱柜调用 add_cabinets 生成配置**。无法确定的字段按推测规则填入合理值。
4. 向用户说明你从图中解读到了哪些信息，以及还有哪些不确定需要确认。

【可用枚举值】
箱柜用途：进线柜、出线柜、电容补偿柜、计量柜、联络柜
箱柜型号：GCK、GCS、MNS、GGD
进出线方式：上进上出、上进下出、下进上出、下进下出
面板类型：默认面板、抽屉面板
面板操作方式：手动机构、电动操作、抽屉式

【元件标准名称】
生成方案时 part_type 必须从以下标准名称中选取（如用户说的名称与标准不完全一致，请匹配最接近的标准名称）；无法匹配时留空：
{_PART_NAMES_STR}

【选型建议】
- 如用户提到额定电流，给出推荐断路器型号
- 如用户提到电动机功率，给出接触器+热继电器组合建议
- 尺寸单位统一为 mm

【元件尺寸参考】
所有尺寸字段**不允许填 0**，按以下参考推测（单位 mm）：
- 框架断路器(ACB): 280×350 | 塑壳断路器(MCCB): 140×250 | 微型断路器(MCB): 80×120
- 交流接触器: 80×120 | 热继电器: 60×80 | 熔断器: 60×80
- 电流互感器: 60×80 | 电压互感器: 80×100 | 电能表: 100×120
- 转换开关: 60×80 | 指示灯: 30×50 | 按钮: 30×50
- 浪涌保护器: 80×100 | 电容器: 120×200 | 电抗器: 120×200
如有具体型号可查到尺寸，以实际尺寸为准。"""


# ──────────────────────────────────────────────────────────────
#  构建 LangGraph ReAct 图
# ──────────────────────────────────────────────────────────────
TOOLS = [add_cabinets, add_panels, add_parts, edit_cabinet, edit_panel, edit_part, get_current_selection, get_scheme_summary]


def build_agent():
    """构建并编译 LangGraph ReAct Agent"""
    llm = _build_llm()
    llm_with_tools = llm.bind_tools(TOOLS)

    async def call_model(state: AgentState) -> dict:
        msgs = state["messages"]
        if not msgs or not isinstance(msgs[0], SystemMessage):
            msgs = [SystemMessage(content=SYSTEM_PROMPT)] + list(msgs)
        response = await llm_with_tools.ainvoke(msgs)
        return {"messages": [response]}

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None):
            return "tools"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", ToolNode(TOOLS))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, ["tools", END])
    graph.add_edge("tools", "agent")
    return graph.compile()


_agent_instance = None


def get_agent():
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = build_agent()
    return _agent_instance
