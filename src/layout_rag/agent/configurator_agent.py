"""
配电柜选配智能体 — 基于 LangGraph ReAct 模式

工具集：
  - add_cabinet   添加柜体（含面板和元件完整信息）
  - add_panel     添加面板到指定/当前柜体
  - add_part      添加元件到指定/当前面板
  - edit_cabinet  修改已有柜体属性
  - edit_panel    修改已有面板属性
  - edit_part     修改已有元件属性
  - delete_cabinet删除指定柜体
  - delete_panel  删除指定面板
  - delete_part   删除指定元件
  - get_current_selection 获取当前选中状态
  - get_schema_summary    获取当前方案摘要
"""
from __future__ import annotations

import json
import os
import uuid as _uuid
from contextvars import ContextVar
from enum import StrEnum
from typing import Annotated, Optional, Literal

from langchain_core.messages import SystemMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, ConfigDict, Field, BeforeValidator
from typing_extensions import TypedDict

from layout_rag.config import load_selection_config

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
    api_key = os.getenv("OPENAI_API_KEY", "")
    base_url = os.getenv("OPENAI_API_BASE", "")
    model_name = os.getenv("MODEL_NAME", "")

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
    current_schema: dict


# ──────────────────────────────────────────────────────────────
#  工具
# ──────────────────────────────────────────────────────────────

# ── 前端选中状态（由 API 层在每次请求前写入） ──
_current_selection_var: ContextVar[dict] = ContextVar(
    "current_selection",
    default={"cabinet_id": "", "panel_id": ""},
)
_current_schema_var: ContextVar[dict] = ContextVar(
    "current_schema",
    default={"cabinets": []},
)
_agent_checkpointer = InMemorySaver()


def set_current_selection(selection: dict) -> None:
    """由 API 层调用，每次请求前写入前端选中的柜体/面板 ID"""
    _current_selection_var.set(selection or {"cabinet_id": "", "panel_id": ""})


def set_current_schema(schema: dict) -> None:
    """由 API 层调用，每次请求前写入前端当前方案"""
    _current_schema_var.set(schema or {"cabinets": []})


def _get_current_selection() -> dict:
    return _current_selection_var.get()


def _get_current_schema() -> dict:
    return _current_schema_var.get()


def _uuid4() -> str:
    return str(_uuid.uuid4())


SELECTION_CONFIG = load_selection_config()
CABINET_USE_OPTIONS = SELECTION_CONFIG.cabinet_use_options
CABINET_MODEL_OPTIONS = SELECTION_CONFIG.cabinet_model_options
PANEL_TYPE_OPTIONS = SELECTION_CONFIG.panel_type_options
WIRING_METHOD_OPTIONS = SELECTION_CONFIG.wiring_method_options
OPERATION_METHOD_OPTIONS = SELECTION_CONFIG.operation_method_options
STANDARD_PART_NAMES = SELECTION_CONFIG.part_type_options


def _format_option_list(options: list[str]) -> str:
    return "、".join(options) if options else "（未配置）"


def _first_option(options: list[str], fallback: str = "") -> str:
    return options[0] if options else fallback


def _make_str_enum(enum_name: str, options: list[str], fallback: str) -> type[StrEnum]:
    values = options or [fallback]
    members = {f"OPTION_{index}": option for index, option in enumerate(values, start=1)}
    return StrEnum(enum_name, members)


CabinetUseOption = _make_str_enum("CabinetUseOption", CABINET_USE_OPTIONS, "出线柜")
CabinetModelOption = _make_str_enum("CabinetModelOption", CABINET_MODEL_OPTIONS, "GGD")
PanelTypeOption = _make_str_enum("PanelTypeOption", PANEL_TYPE_OPTIONS, "默认面板")
WiringMethodOption = _make_str_enum("WiringMethodOption", WIRING_METHOD_OPTIONS, "上进上出")
OperationMethodOption = _make_str_enum("OperationMethodOption", OPERATION_METHOD_OPTIONS, "手动机构")
PartTypeOption = _make_str_enum("PartTypeOption", STANDARD_PART_NAMES, "")

OptionalWiringMethodOption = Annotated[
    WiringMethodOption | Literal[""],
    BeforeValidator(lambda v: v if v in WIRING_METHOD_OPTIONS else "")
]
OptionalOperationMethodOption = Annotated[
    OperationMethodOption | Literal[""],
    BeforeValidator(lambda v: v if v in OPERATION_METHOD_OPTIONS else "")
]
OptionalPartTypeOption = Annotated[
    PartTypeOption | Literal[""],
    BeforeValidator(lambda v: v if v in STANDARD_PART_NAMES else "")
]


class ConfiguredInputModel(BaseModel):
    model_config = ConfigDict(use_enum_values=True)


# ── 结构化输入 ──
class PartInput(ConfiguredInputModel):
    order: int = Field(default=0, description="序号，用于前端排序，提取多项时请严格按顺序递增给出")
    part_type: OptionalPartTypeOption = Field(
        default="",
        description="元件标准名称，必须从共享选型配置的标准名称列表中选取；无法识别时留空",
    )
    part_model: str = Field(default="", description="元件型号规格，如 DW15-630；无法识别时留空")

    part_width: int = Field(default=80, description="元件宽度(mm)，根据元件类型推测合理值")
    part_height: int = Field(default=100, description="元件高度(mm)，根据元件类型推测合理值")

class PanelInput(ConfiguredInputModel):
    order: int = Field(default=0, description="序号，用于前端排序，提取多项时请严格按顺序递增给出")
    panel_type: PanelTypeOption = Field(
        default=PanelTypeOption(_first_option(PANEL_TYPE_OPTIONS, "默认面板")),
        description=f"面板类型；配置可选值：{_format_option_list(PANEL_TYPE_OPTIONS)}",
    )
    operation_method: OptionalOperationMethodOption = Field(
        default="",
        description=f"操作方式；配置可选值：{_format_option_list(OPERATION_METHOD_OPTIONS)}；无法识别时留空",
    )
    main_circuit_current: Optional[int] = Field(default=None, description="主回路电流(A)，未知时留空")
    main_circuit_poles: Optional[int] = Field(default=None, description="主回路极数，未知时留空")
    panel_width: int = Field(default=800, description="面板宽度(mm)，未知时按柜体宽度推测")
    panel_height: int = Field(default=2200, description="面板高度(mm)，未知时按柜体高度推测")
    parts: list[PartInput] = Field(default_factory=list)

class CabinetInput(ConfiguredInputModel):
    order: int = Field(default=0, description="序号，用于前端排序，提取多项时请严格按顺序递增给出")
    cabinet_name: str = Field(default="", description="柜名/柜编号：如 1AL")
    cabinet_use: CabinetUseOption = Field(
        default=CabinetUseOption(_first_option(CABINET_USE_OPTIONS, "出线柜")),
        description=f"柜用途；配置可选值：{_format_option_list(CABINET_USE_OPTIONS)}；根据元件配置推测",
    )
    cabinet_model: CabinetModelOption = Field(
        default=CabinetModelOption(_first_option(CABINET_MODEL_OPTIONS, "GGD")),
        description=f"柜型号；配置可选值：{_format_option_list(CABINET_MODEL_OPTIONS)}；根据用途和面板类型推测",
    )
    wiring_method: OptionalWiringMethodOption = Field(
        default="",
        description=f"进出线方式；配置可选值：{_format_option_list(WIRING_METHOD_OPTIONS)}；无法识别时留空",
    )
    cabinet_width: int = Field(default=800, description="柜宽(mm)，未知时按柜型推测常见值")
    cabinet_height: int = Field(default=2200, description="柜高(mm)，未知时按柜型推测常见值")
    panels: list[PanelInput] = Field(default_factory=list)

class AddCabinetsInput(BaseModel):
    cabinets: list[CabinetInput] = Field(description="新添加的柜体列表")

class AddPanelsInput(BaseModel):
    cabinet_id: str = Field(default="", description="目标柜体 ID；留空则添加到当前选中的柜体")
    panels: list[PanelInput] = Field(description="新添加的面板列表")

class AddPartsInput(BaseModel):
    panel_id: str = Field(default="", description="目标面板 ID；留空则添加到当前选中的面板")
    parts: list[PartInput] = Field(description="新添加的元件列表")


class EditCabinetInput(BaseModel):
    cabinet_id: str = Field(description="要修改的柜体 ID（定位用，通过 get_current_selection 或 get_schema_summary 获取）")
    cabinet_name: Optional[str] = Field(default=None, description="柜名/柜编号：如 1AL")
    cabinet_use: Optional[Annotated[CabinetUseOption | Literal[""], BeforeValidator(lambda v: v if v in CABINET_USE_OPTIONS else "")]] = Field(
        default=None, description=f"柜用途；配置可选值：{_format_option_list(CABINET_USE_OPTIONS)}"
    )
    cabinet_model: Optional[Annotated[CabinetModelOption | Literal[""], BeforeValidator(lambda v: v if v in CABINET_MODEL_OPTIONS else "")]] = Field(
        default=None, description=f"柜型号；配置可选值：{_format_option_list(CABINET_MODEL_OPTIONS)}"
    )
    wiring_method: Optional[OptionalWiringMethodOption] = Field(
        default=None, description=f"进出线方式；配置可选值：{_format_option_list(WIRING_METHOD_OPTIONS)}"
    )
    cabinet_width: Optional[int] = Field(default=None, description="柜宽(mm)")
    cabinet_height: Optional[int] = Field(default=None, description="柜高(mm)")


class EditPanelInput(BaseModel):
    panel_id: str = Field(description="要修改的面板 ID（定位用，通过 get_current_selection 或 get_schema_summary 获取）")
    panel_type: Optional[Annotated[PanelTypeOption | Literal[""], BeforeValidator(lambda v: v if v in PANEL_TYPE_OPTIONS else "")]] = Field(
        default=None, description=f"面板类型；配置可选值：{_format_option_list(PANEL_TYPE_OPTIONS)}"
    )
    operation_method: Optional[OptionalOperationMethodOption] = Field(
        default=None, description=f"操作方式；配置可选值：{_format_option_list(OPERATION_METHOD_OPTIONS)}"
    )
    main_circuit_current: Optional[int] = Field(default=None, description="主回路电流(A)")
    main_circuit_poles: Optional[int] = Field(default=None, description="主回路极数")
    panel_width: Optional[int] = Field(default=None, description="面板宽度(mm)")
    panel_height: Optional[int] = Field(default=None, description="面板高度(mm)")


class EditPartInput(BaseModel):
    part_id: str = Field(description="要修改的元件 ID（定位用，通过 get_current_selection 或 get_schema_summary 获取）")
    part_type: Optional[OptionalPartTypeOption] = Field(
        default=None, description="元件标准名称，必须从选型配置列表选取；无法识别时留空"
    )
    part_model: Optional[str] = Field(default=None, description="元件型号规格，如 DW15-630；无法识别时留空")
    part_width: Optional[int] = Field(default=None, description="元件宽度(mm)")
    part_height: Optional[int] = Field(default=None, description="元件高度(mm)")


class DeleteCabinetInput(BaseModel):
    cabinet_id: str = Field(description="要删除的柜体 ID")

class DeletePanelInput(BaseModel):
    panel_id: str = Field(description="要删除的面板 ID")

class DeletePartInput(BaseModel):
    part_id: str = Field(description="要删除的元件 ID")


def _assign_ids_to_panel(panel_dict: dict) -> dict:
    """为面板及其元件自动分配 ID"""
    panel_dict["panel_id"] = _uuid4()
    for pt in panel_dict.get("parts", []):
        pt["part_id"] = _uuid4()
    return panel_dict


@tool(args_schema=AddCabinetsInput)
async def add_cabinets(**kwargs) -> str:
    """批量添加柜体（含面板和元件完整信息）。当用户描述新柜体时调用，支持一次添加多个，并支持嵌套面板和元件。id 由系统自动生成。"""
    cabs_input = AddCabinetsInput(**kwargs).model_dump()
    cabs = cabs_input.get("cabinets", [])
    for cab in cabs:
        cab["cabinet_id"] = _uuid4()
        for p in cab.get("panels", []):
            _assign_ids_to_panel(p)

    parts_n = sum(len(p.get("parts", [])) for cab in cabs for p in cab.get("panels", []))
    msg = f"已批量添加 {len(cabs)} 个柜体（共包含 {parts_n} 个初始元件）"
    return json.dumps(
        {
            "action": "add_cabinets",
            "cabinets": cabs,
            "message": msg,
        },
        ensure_ascii=False,
    )


@tool(args_schema=AddPanelsInput)
async def add_panels(**kwargs) -> str:
    """批量添加多个面板（含元件完整信息）到指定柜体。cabinet_id 留空则添加到当前选中的柜体。"""
    input_data = AddPanelsInput(**kwargs)
    target_cab_id = input_data.cabinet_id or _get_current_selection().get("cabinet_id", "")
    if not target_cab_id:
        return json.dumps({"action": "error", "message": "未指定目标柜体且当前未选中任何柜体，请先选中一个柜体"}, ensure_ascii=False)

    panels = input_data.model_dump(exclude={"cabinet_id"}).get("panels", [])
    for p in panels:
        _assign_ids_to_panel(p)

    return json.dumps(
        {
            "action": "add_panels",
            "cabinet_id": target_cab_id,
            "panels": panels,
            "message": f"已批量添加 {len(panels)} 个面板到柜体 {target_cab_id}",
        },
        ensure_ascii=False,
    )


@tool(args_schema=AddPartsInput)
async def add_parts(**kwargs) -> str:
    """批量添加多个元件到指定面板。panel_id 留空则添加到当前选中的面板。"""
    input_data = AddPartsInput(**kwargs)
    target_pan_id = input_data.panel_id or _get_current_selection().get("panel_id", "")
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


@tool(args_schema=EditCabinetInput)
async def edit_cabinet(**kwargs) -> str:
    """修改已有柜体的属性（仅传需要修改的字段）。"""
    cabinet_id = kwargs.pop("cabinet_id")
    updates = {k: v for k, v in kwargs.items() if v is not None}

    return json.dumps(
        {
            "action": "edit_cabinet",
            "cabinet_id": cabinet_id,
            "updates": updates,
            "message": f"已更新柜体 {cabinet_id}：{updates}",
        },
        ensure_ascii=False,
    )


@tool(args_schema=EditPanelInput)
async def edit_panel(**kwargs) -> str:
    """修改已有面板的属性。"""
    panel_id = kwargs.pop("panel_id")
    updates = {k: v for k, v in kwargs.items() if v is not None}

    return json.dumps(
        {
            "action": "edit_panel",
            "panel_id": panel_id,
            "updates": updates,
            "message": f"已更新面板 {panel_id}：{updates}",
        },
        ensure_ascii=False,
    )


@tool(args_schema=EditPartInput)
async def edit_part(**kwargs) -> str:
    """修改已有元件的属性。"""
    part_id = kwargs.pop("part_id")
    updates = {k: v for k, v in kwargs.items() if v is not None}

    return json.dumps(
        {
            "action": "edit_part",
            "part_id": part_id,
            "updates": updates,
            "message": f"已更新元件 {part_id}：{updates}",
        },
        ensure_ascii=False,
    )


@tool(args_schema=DeleteCabinetInput)
async def delete_cabinet(cabinet_id: str) -> str:
    """删除指定的柜体。"""
    return json.dumps(
        {
            "action": "delete_cabinet",
            "cabinet_id": cabinet_id,
            "message": f"已删除柜体 {cabinet_id}",
        },
        ensure_ascii=False,
    )


@tool(args_schema=DeletePanelInput)
async def delete_panel(panel_id: str) -> str:
    """删除指定的面板。"""
    return json.dumps(
        {
            "action": "delete_panel",
            "panel_id": panel_id,
            "message": f"已删除面板 {panel_id}",
        },
        ensure_ascii=False,
    )


@tool(args_schema=DeletePartInput)
async def delete_part(part_id: str) -> str:
    """删除指定的元件。"""
    return json.dumps(
        {
            "action": "delete_part",
            "part_id": part_id,
            "message": f"已删除元件 {part_id}",
        },
        ensure_ascii=False,
    )

@tool
async def get_current_selection() -> str:
    """
    获取用户当前在界面上选中的柜体和面板的完整信息（含 ID、名称、面板列表、元件列表）。
    当用户说"当前面板"/"当前柜体"或要编辑某个元件时，先调用此工具获取目标 ID。
    """
    current_selection = _get_current_selection()
    current_schema = _get_current_schema()
    cab_id = current_selection.get("cabinet_id", "")
    pan_id = current_selection.get("panel_id", "")
    lines: list[str] = []

    # 在当前方案中查找选中的柜体
    sel_cabinet = None
    for c in current_schema.get("cabinets", []):
        if c.get("cabinet_id") == cab_id:
            sel_cabinet = c
            break

    if sel_cabinet:
        lines.append(
            f"当前选中柜体: [{cab_id}] {sel_cabinet.get('cabinet_name','?')}"
            f"（{sel_cabinet.get('cabinet_use','?')}，{sel_cabinet.get('cabinet_model','?')}）"
        )
        # 列出该柜体的所有面板
        for pn in sel_cabinet.get("panels", []):
            pid = pn.get('panel_id', '?')
            marker = " ← 当前选中" if pid == pan_id else ""
            lines.append(f"  面板 [{pid}] {pn.get('panel_type','?')}{marker}")
            for pt in pn.get("parts", []):
                lines.append(
                    f"    元件 [{pt.get('part_id','?')}] {pt.get('part_type','?')} "
                    f"{pt.get('part_model','')}"
                )
    else:
        lines.append("当前未选中任何柜体" if not cab_id else f"选中的柜体 ID {cab_id} 在方案中未找到")

    if not pan_id:
        lines.append("当前未选中任何面板")

    return "\n".join(lines)


@tool
async def get_schema_summary() -> str:
    """
    获取当前方案的统计摘要，帮助了解已有配置。无需传参，直接读取当前方案。
    """
    cabinets = _get_current_schema().get("cabinets", [])
    if not cabinets:
        return "当前方案为空，尚未配置任何柜体。"
    lines = [f"当前方案共 {len(cabinets)} 台柜体："]
    for c in cabinets:
        panels = c.get("panels", [])
        parts_total = sum(len(pn.get("parts", [])) for pn in panels)
        cab_id = c.get('cabinet_id', '?')
        lines.append(
            f"  · [{cab_id}] {c.get('cabinet_name','?')}（{c.get('cabinet_use','?')}，"
            f"{c.get('cabinet_model','?')}）— {len(panels)} 个面板，{parts_total} 个元件"
        )
        for pn in panels:
            pan_id = pn.get('panel_id', '?')
            pn_parts = pn.get('parts', [])
            lines.append(
                f"      面板 [{pan_id}] {pn.get('panel_type','?')} — {len(pn_parts)} 个元件"
            )
            for pt in pn_parts:
                pt_id = pt.get('part_id', '?')
                lines.append(
                    f"        元件 [{pt_id}] {pt.get('part_type','?')} {pt.get('part_model','')}"
                )
    return "\n".join(lines)


# ──────────────────────────────────────────────────────────────
#  系统提示词
# ──────────────────────────────────────────────────────────────
SYSTEM_PROMPT = """你是一个专业的配电柜选配助手，帮助用户设计低压配电系统方案。

【工具使用】
1. 用户描述新方案或新增柜体时，调用 add_cabinets，一次可以创建多个柜体，并传入完整的面板和元件结构。
2. 用户给已有柜体新增面板时，调用 add_panels；给已有面板新增元件时，调用 add_parts。用户未指定目标时，优先使用当前选中对象。
3. 用户修改或删除已有内容时，调用 edit_* 或 delete_* 工具，并始终使用 ID 定位。
4. 用户提到“当前面板”或“当前柜体”时，先调用 get_current_selection；用户通过名称描述目标时，先调用 get_schema_summary 找到对应 ID。
5. 每次工具调用后，简要说明执行了什么。

【字段约束】
1. 所有枚举字段和 part_type 必须严格使用工具参数 schema 中给出的可选值，不要自造新值。
2. 对于允许留空的字段，如无法识别，使用空字符串。
3. 如果用户没有明确指定，优先使用工具 schema 中的默认值；只有默认值明显不适用时，才根据上下文推测。
4. 推测得到的值在回复中标注“（推测）”，提示用户确认或修改。

【推测规则】
1. 柜用途根据元件配置推测：主进线断路器通常对应进线柜，多回路出线通常对应出线柜，含电容器通常对应电容补偿柜。
2. 柜型号可为空；柜体常见尺寸为 800×2200mm，抽屉柜常见 600/800×2200mm。
3. 默认面板通常与柜体同尺寸；抽屉面板可按回路数拆分，高度优先按模数推断，否则按柜体总高度均分向下取整。
4. 元件名称无法匹配标准名时留空；元件型号无法识别时留空。
5. 所有尺寸字段不得为 0；若无法识别，按合理常见值推测。

【面板规则】
1. 出线柜或抽屉柜中，一个出线回路对应一个独立抽屉面板。
2. 其他柜型通常只有一个默认面板，元件平铺安装在该面板上。
3. 如果无法识别面板尺寸，必须使用所属柜体的宽度和高度。
4. 为柜体、面板、元件的 order 字段分配递增数字，保持前端图纸阅读顺序。

【图片分析】
1. 当用户发送配电系统图、单线图、系统图、配电柜照片、元件清单表等图片时，先识别柜体数量、柜型、回路数量、元件型号规格和额定参数。
2. 对于出线柜，要根据识别到的回路数创建对应数量的抽屉面板。
3. 提取出关键信息后，直接调用 add_cabinets 生成配置；不确定字段按上述规则合理补全。
4. 回复时说明已识别的信息，以及仍需用户确认的不确定项。
"""


# ──────────────────────────────────────────────────────────────
#  构建 LangGraph ReAct 图
# ──────────────────────────────────────────────────────────────
TOOLS = [add_cabinets, add_panels, add_parts, edit_cabinet, edit_panel, edit_part, delete_cabinet, delete_panel, delete_part, get_current_selection, get_schema_summary]


def build_agent(checkpointer: InMemorySaver | None = None):
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
    return graph.compile(checkpointer=checkpointer or _agent_checkpointer)


_agent_instance = None


def get_agent():
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = build_agent()
    return _agent_instance
