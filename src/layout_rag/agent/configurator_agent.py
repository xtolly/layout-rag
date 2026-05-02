"""
配置智能体 — 基于 LangGraph ReAct 模式（领域驱动版本）

所有字段定义、可选值、提示词均从 domain.ui_schema() 动态获取，
不再硬编码任何业务相关的属性或选项。
"""
from __future__ import annotations

import json
import os
import uuid as _uuid
from contextvars import ContextVar
from enum import StrEnum
from typing import Annotated, Any, Optional, Literal

from langchain_core.messages import SystemMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel, ConfigDict, Field, BeforeValidator
from typing_extensions import TypedDict

from dotenv import load_dotenv

load_dotenv()

# ──────────────────────────────────────────────────────────────
#  Qwen LLM
# ──────────────────────────────────────────────────────────────

def _make_openai_cls():
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
    api_key = os.getenv("OPENAI_API_KEY", "")
    base_url = os.getenv("OPENAI_API_BASE", "")
    model_name = os.getenv("MODEL_NAME", "")

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
#  前端选中状态（由 API 层在每次请求前写入）
# ──────────────────────────────────────────────────────────────
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
    _current_selection_var.set(selection or {"cabinet_id": "", "panel_id": ""})


def set_current_schema(schema: dict) -> None:
    _current_schema_var.set(schema or {"cabinets": []})


def _get_current_selection() -> dict:
    return _current_selection_var.get()


def _get_current_schema() -> dict:
    return _current_schema_var.get()


def _uuid4() -> str:
    return str(_uuid.uuid4())


# ──────────────────────────────────────────────────────────────
#  动态模型生成
# ──────────────────────────────────────────────────────────────

def _make_str_enum(enum_name: str, options: list[str], fallback: str) -> type[StrEnum]:
    values = options or [fallback]
    members = {f"OPTION_{i}": v for i, v in enumerate(values, start=1)}
    return StrEnum(enum_name, members)


def _format_option_list(options: list[str]) -> str:
    return "、".join(options) if options else "（未配置）"


def _first_option(options: list[str], fallback: str = "") -> str:
    return options[0] if options else fallback


def _build_input_models(ui_schema: dict, part_types: list[str]) -> dict[str, type[BaseModel]]:
    """
    从 ui_schema 动态生成所有 Pydantic 输入模型。

    返回 dict，包含：
      PartInput, PanelInput, CabinetInput,
      EditPartInput, EditPanelInput, EditCabinetInput,
      AddCabinetsInput, AddPanelsInput, AddPartsInput,
      DeleteCabinetInput, DeletePanelInput, DeletePartInput
    """
    model_config = ConfigDict(use_enum_values=True)

    # ── 按字段组索引 ──
    cabinet_fields = ui_schema.get("cabinet_fields", [])
    panel_fields = ui_schema.get("panel_fields", [])
    part_fields = ui_schema.get("part_fields", [])

    # ── 收集 select 字段的枚举映射 ──
    enum_map: dict[str, type[StrEnum]] = {}
    select_options: dict[str, list[str]] = {}

    def _register_select(field_def: dict):
        key = field_def["key"]
        opts = field_def.get("options", [])
        if not opts:
            return
        enum_name = f"Enum_{key}"
        fallback = opts[0]
        enum_map[key] = _make_str_enum(enum_name, opts, fallback)
        select_options[key] = opts

    for f in cabinet_fields + panel_fields + part_fields:
        if f.get("type") == "select":
            _register_select(f)

    # ── 字段类型映射 ──
    def _field_type_annotation(field_def: dict, for_edit: bool = False):
        """返回 (type_annotation, default_value, description_extra)"""
        key = field_def["key"]
        ftype = field_def.get("type", "text")
        label = field_def.get("label", key)
        default = field_def.get("default")

        if ftype == "select" and key in enum_map:
            enum_cls = enum_map[key]
            opts = select_options[key]
            desc = f"{label}；可选值：{_format_option_list(opts)}"
            if for_edit:
                opt_type = Annotated[
                    enum_cls | Literal[""],
                    BeforeValidator(lambda v, _opts=opts: v if v in _opts else "")
                ]
                return Optional[opt_type], None, desc
            else:
                return enum_cls, enum_cls(_first_option(opts)), desc

        elif ftype == "number":
            if for_edit:
                return Optional[int], None, label
            return int, default if default is not None else 0, label

        elif ftype == "boolean":
            if for_edit:
                return Optional[bool], None, label
            return bool, default if default is not None else False, label

        else:  # text
            if for_edit:
                return Optional[str], None, label
            return str, default if default is not None else "", label

    # ── 构建 PartInput ──
    part_attrs = {"__annotations__": {}, "model_config": model_config}
    part_attrs["order"] = Field(default=0, description="序号，用于前端排序，提取多项时请严格按顺序递增给出")
    part_attrs["__annotations__"]["order"] = int
    for f in part_fields:
        key = f["key"]
        ann, default_val, desc = _field_type_annotation(f)
        part_attrs["__annotations__"][key] = ann
        part_attrs[key] = Field(default=default_val, description=desc)
    PartInput = type("PartInput", (BaseModel,), part_attrs)

    # ── 构建 PanelInput ──
    panel_attrs = {"__annotations__": {}, "model_config": model_config}
    panel_attrs["order"] = Field(default=0, description="序号，用于前端排序，提取多项时请严格按顺序递增给出")
    panel_attrs["__annotations__"]["order"] = int
    for f in panel_fields:
        key = f["key"]
        ann, default_val, desc = _field_type_annotation(f)
        panel_attrs["__annotations__"][key] = ann
        panel_attrs[key] = Field(default=default_val, description=desc)
    panel_attrs["__annotations__"]["parts"] = list[PartInput]
    panel_attrs["parts"] = Field(default_factory=list, description="面板下的元件列表")
    PanelInput = type("PanelInput", (BaseModel,), panel_attrs)

    # ── 构建 CabinetInput ──
    cab_attrs = {"__annotations__": {}, "model_config": model_config}
    cab_attrs["order"] = Field(default=0, description="序号，用于前端排序，提取多项时请严格按顺序递增给出")
    cab_attrs["__annotations__"]["order"] = int
    for f in cabinet_fields:
        key = f["key"]
        ann, default_val, desc = _field_type_annotation(f)
        cab_attrs["__annotations__"][key] = ann
        cab_attrs[key] = Field(default=default_val, description=desc)
    cab_attrs["__annotations__"]["panels"] = list[PanelInput]
    cab_attrs["panels"] = Field(default_factory=list, description="柜体下的面板列表")
    CabinetInput = type("CabinetInput", (BaseModel,), cab_attrs)

    # ── 构建 Edit 模型（所有字段 Optional） ──
    def _build_edit_model(name: str, fields: list[dict], id_field: str, id_desc: str):
        attrs = {"__annotations__": {}, "model_config": ConfigDict()}
        attrs["__annotations__"][id_field] = str
        attrs[id_field] = Field(description=id_desc)
        for f in fields:
            key = f["key"]
            ann, _, desc = _field_type_annotation(f, for_edit=True)
            attrs["__annotations__"][key] = ann
            attrs[key] = Field(default=None, description=desc)
        return type(name, (BaseModel,), attrs)

    EditCabinetInput = _build_edit_model(
        "EditCabinetInput", cabinet_fields, "cabinet_id", "要修改的柜体 ID"
    )
    EditPanelInput = _build_edit_model(
        "EditPanelInput", panel_fields, "panel_id", "要修改的面板 ID"
    )
    EditPartInput = _build_edit_model(
        "EditPartInput", part_fields, "part_id", "要修改的元件 ID"
    )

    # ── 容器模型 ──
    AddCabinetsInput = type("AddCabinetsInput", (BaseModel,), {
        "__annotations__": {"cabinets": list[CabinetInput]},
        "cabinets": Field(description="新添加的柜体列表"),
    })
    AddPanelsInput = type("AddPanelsInput", (BaseModel,), {
        "__annotations__": {"cabinet_id": str, "panels": list[PanelInput]},
        "cabinet_id": Field(default="", description="目标柜体 ID；留空则添加到当前选中的柜体"),
        "panels": Field(description="新添加的面板列表"),
    })
    AddPartsInput = type("AddPartsInput", (BaseModel,), {
        "__annotations__": {"panel_id": str, "parts": list[PartInput]},
        "panel_id": Field(default="", description="目标面板 ID；留空则添加到当前选中的面板"),
        "parts": Field(description="新添加的元件列表"),
    })
    DeleteCabinetInput = type("DeleteCabinetInput", (BaseModel,), {
        "__annotations__": {"cabinet_id": str},
        "cabinet_id": Field(description="要删除的柜体 ID"),
    })
    DeletePanelInput = type("DeletePanelInput", (BaseModel,), {
        "__annotations__": {"panel_id": str},
        "panel_id": Field(description="要删除的面板 ID"),
    })
    DeletePartInput = type("DeletePartInput", (BaseModel,), {
        "__annotations__": {"part_id": str},
        "part_id": Field(description="要删除的元件 ID"),
    })

    return {
        "PartInput": PartInput,
        "PanelInput": PanelInput,
        "CabinetInput": CabinetInput,
        "EditCabinetInput": EditCabinetInput,
        "EditPanelInput": EditPanelInput,
        "EditPartInput": EditPartInput,
        "AddCabinetsInput": AddCabinetsInput,
        "AddPanelsInput": AddPanelsInput,
        "AddPartsInput": AddPartsInput,
        "DeleteCabinetInput": DeleteCabinetInput,
        "DeletePanelInput": DeletePanelInput,
        "DeletePartInput": DeletePartInput,
    }


# ──────────────────────────────────────────────────────────────
#  动态提示词生成
# ──────────────────────────────────────────────────────────────

def _build_system_prompt(ui_schema: dict, part_types: list[str]) -> str:
    """从 ui_schema 构建领域无关的系统提示词。"""

    # ── 字段说明 ──
    def _field_docs(fields: list[dict], entity_name: str) -> list[str]:
        lines = []
        for f in fields:
            key = f["key"]
            label = f.get("label", key)
            ftype = f.get("type", "text")
            if ftype == "select":
                opts = f.get("options", [])
                lines.append(f"  - {label}（{key}）：可选值 {_format_option_list(opts)}")
            elif ftype == "number":
                default = f.get("default")
                hint = f"，默认 {default}" if default is not None else ""
                lines.append(f"  - {label}（{key}）：数值类型{hint}")
            elif ftype == "boolean":
                lines.append(f"  - {label}（{key}）：布尔类型")
            else:
                lines.append(f"  - {label}（{key}）：文本类型")
        return lines

    cab_docs = _field_docs(ui_schema.get("cabinet_fields", []), "柜体")
    pan_docs = _field_docs(ui_schema.get("panel_fields", []), "面板")
    part_docs = _field_docs(ui_schema.get("part_fields", []), "元件")

    part_types_str = _format_option_list(part_types) if part_types else "（未配置）"

    return f"""你是一个专业的配置助手，帮助用户设计方案。

【工具使用】
1. 用户描述新方案或新增配置时，调用 add_cabinets，一次可以创建多个，并传入完整的面板和元件结构。
2. 用户给已有配置新增面板时，调用 add_panels；给已有面板新增元件时，调用 add_parts。用户未指定目标时，优先使用当前选中对象。
3. 用户修改或删除已有内容时，调用 edit_* 或 delete_* 工具，并始终使用 ID 定位。
4. 用户提到"当前面板"或"当前柜体"时，先调用 get_current_selection；用户通过名称描述目标时，先调用 get_schema_summary 找到对应 ID。
5. 每次工具调用后，简要说明执行了什么。

【字段约束】
1. 所有枚举字段必须严格使用工具参数 schema 中给出的可选值，不要自造新值。
2. 对于允许留空的字段，如无法识别，使用空字符串。
3. 如果用户没有明确指定，优先使用工具 schema 中的默认值；只有默认值明显不适用时，才根据上下文推测。
4. 推测得到的值在回复中标注"（推测）"，提示用户确认或修改。

【字段定义】
柜体字段：
{chr(10).join(cab_docs)}

面板字段：
{chr(10).join(pan_docs)}

元件字段：
{chr(10).join(part_docs)}

已知元件类型：{part_types_str}

【推测规则】
1. 根据已有元件和上下文合理推测配置属性，不要凭空编造。
2. 尺寸字段不得为 0；若无法识别，按合理常见值推测。
3. 无法匹配已知类型或型号时留空。
4. 为各层级的 order 字段分配递增数字，保持合理的排列顺序。

【图片分析】
1. 当用户发送图片时，先识别其中的配置信息、数量、规格和参数。
2. 提取关键信息后，直接调用 add_cabinets 生成配置；不确定字段按上述规则合理补全。
3. 回复时说明已识别的信息，以及仍需用户确认的不确定项。
"""


# ──────────────────────────────────────────────────────────────
#  工具定义（接收动态模型类）
# ──────────────────────────────────────────────────────────────

def _assign_ids_to_panel(panel_dict: dict) -> dict:
    panel_dict["panel_id"] = _uuid4()
    for pt in panel_dict.get("parts", []):
        pt["part_id"] = _uuid4()
    return panel_dict


def _build_tools(models: dict[str, type[BaseModel]]) -> list:
    """根据动态生成的模型构建工具列表。"""
    AddCabinetsInput = models["AddCabinetsInput"]
    AddPanelsInput = models["AddPanelsInput"]
    AddPartsInput = models["AddPartsInput"]
    EditCabinetInput = models["EditCabinetInput"]
    EditPanelInput = models["EditPanelInput"]
    EditPartInput = models["EditPartInput"]
    DeleteCabinetInput = models["DeleteCabinetInput"]
    DeletePanelInput = models["DeletePanelInput"]
    DeletePartInput = models["DeletePartInput"]

    @tool(args_schema=AddCabinetsInput)
    async def add_cabinets(**kwargs) -> str:
        """批量添加配置（含面板和元件完整信息）。支持一次添加多个，并支持嵌套面板和元件。id 由系统自动生成。"""
        cabs_input = AddCabinetsInput(**kwargs).model_dump()
        cabs = cabs_input.get("cabinets", [])
        for cab in cabs:
            cab["cabinet_id"] = _uuid4()
            for p in cab.get("panels", []):
                _assign_ids_to_panel(p)
        parts_n = sum(len(p.get("parts", [])) for cab in cabs for p in cab.get("panels", []))
        return json.dumps(
            {"action": "add_cabinets", "cabinets": cabs, "message": f"已批量添加 {len(cabs)} 个配置（共包含 {parts_n} 个初始元件）"},
            ensure_ascii=False,
        )

    @tool(args_schema=AddPanelsInput)
    async def add_panels(**kwargs) -> str:
        """批量添加多个面板（含元件完整信息）到指定配置。cabinet_id 留空则添加到当前选中的配置。"""
        input_data = AddPanelsInput(**kwargs)
        target_cab_id = input_data.cabinet_id or _get_current_selection().get("cabinet_id", "")
        if not target_cab_id:
            return json.dumps({"action": "error", "message": "未指定目标且当前未选中任何配置，请先选中一个"}, ensure_ascii=False)
        panels = input_data.model_dump(exclude={"cabinet_id"}).get("panels", [])
        for p in panels:
            _assign_ids_to_panel(p)
        return json.dumps(
            {"action": "add_panels", "cabinet_id": target_cab_id, "panels": panels, "message": f"已批量添加 {len(panels)} 个面板"},
            ensure_ascii=False,
        )

    @tool(args_schema=AddPartsInput)
    async def add_parts(**kwargs) -> str:
        """批量添加多个元件到指定面板。panel_id 留空则添加到当前选中的面板。"""
        input_data = AddPartsInput(**kwargs)
        target_pan_id = input_data.panel_id or _get_current_selection().get("panel_id", "")
        if not target_pan_id:
            return json.dumps({"action": "error", "message": "未指定目标面板且当前未选中任何面板，请先选中一个"}, ensure_ascii=False)
        parts = input_data.model_dump(exclude={"panel_id"}).get("parts", [])
        for pt in parts:
            pt["part_id"] = _uuid4()
        return json.dumps(
            {"action": "add_parts", "panel_id": target_pan_id, "parts": parts, "message": f"已批量添加 {len(parts)} 个元件"},
            ensure_ascii=False,
        )

    @tool(args_schema=EditCabinetInput)
    async def edit_cabinet(**kwargs) -> str:
        """修改已有配置的属性（仅传需要修改的字段）。"""
        cabinet_id = kwargs.pop("cabinet_id")
        updates = {k: v for k, v in kwargs.items() if v is not None}
        return json.dumps(
            {"action": "edit_cabinet", "cabinet_id": cabinet_id, "updates": updates, "message": f"已更新配置 {cabinet_id}：{updates}"},
            ensure_ascii=False,
        )

    @tool(args_schema=EditPanelInput)
    async def edit_panel(**kwargs) -> str:
        """修改已有面板的属性。"""
        panel_id = kwargs.pop("panel_id")
        updates = {k: v for k, v in kwargs.items() if v is not None}
        return json.dumps(
            {"action": "edit_panel", "panel_id": panel_id, "updates": updates, "message": f"已更新面板 {panel_id}：{updates}"},
            ensure_ascii=False,
        )

    @tool(args_schema=EditPartInput)
    async def edit_part(**kwargs) -> str:
        """修改已有元件的属性。"""
        part_id = kwargs.pop("part_id")
        updates = {k: v for k, v in kwargs.items() if v is not None}
        return json.dumps(
            {"action": "edit_part", "part_id": part_id, "updates": updates, "message": f"已更新元件 {part_id}：{updates}"},
            ensure_ascii=False,
        )

    @tool(args_schema=DeleteCabinetInput)
    async def delete_cabinet(cabinet_id: str) -> str:
        """删除指定的配置。"""
        return json.dumps({"action": "delete_cabinet", "cabinet_id": cabinet_id, "message": f"已删除配置 {cabinet_id}"}, ensure_ascii=False)

    @tool(args_schema=DeletePanelInput)
    async def delete_panel(panel_id: str) -> str:
        """删除指定的面板。"""
        return json.dumps({"action": "delete_panel", "panel_id": panel_id, "message": f"已删除面板 {panel_id}"}, ensure_ascii=False)

    @tool(args_schema=DeletePartInput)
    async def delete_part(part_id: str) -> str:
        """删除指定的元件。"""
        return json.dumps({"action": "delete_part", "part_id": part_id, "message": f"已删除元件 {part_id}"}, ensure_ascii=False)

    @tool
    async def get_current_selection() -> str:
        """
        获取用户当前在界面上选中的配置和面板的完整信息（含 ID、名称、面板列表、元件列表）。
        当用户说"当前面板"/"当前配置"或要编辑某个元件时，先调用此工具获取目标 ID。
        """
        current_selection = _get_current_selection()
        current_schema = _get_current_schema()
        cab_id = current_selection.get("cabinet_id", "")
        pan_id = current_selection.get("panel_id", "")
        lines: list[str] = []
        sel_cabinet = None
        for c in current_schema.get("cabinets", []):
            if c.get("cabinet_id") == cab_id:
                sel_cabinet = c
                break
        if sel_cabinet:
            name = sel_cabinet.get("cabinet_name") or sel_cabinet.get("box_classify") or "?"
            lines.append(f"当前选中: [{cab_id}] {name}")
            for pn in sel_cabinet.get("panels", []):
                pid = pn.get("panel_id", "?")
                marker = " ← 当前选中" if pid == pan_id else ""
                lines.append(f"  面板 [{pid}] {pn.get('panel_type', '?')}{marker}")
                for pt in pn.get("parts", []):
                    lines.append(f"    元件 [{pt.get('part_id', '?')}] {pt.get('part_type', '?')} {pt.get('part_model', '')}")
        else:
            lines.append("当前未选中任何配置" if not cab_id else f"选中的配置 ID {cab_id} 在方案中未找到")
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
            return "当前方案为空，尚未配置任何内容。"
        lines = [f"当前方案共 {len(cabinets)} 个配置："]
        for c in cabinets:
            panels = c.get("panels", [])
            parts_total = sum(len(pn.get("parts", [])) for pn in panels)
            cab_id = c.get("cabinet_id", "?")
            name = c.get("cabinet_name") or c.get("box_classify") or "?"
            lines.append(f"  · [{cab_id}] {name} — {len(panels)} 个面板，{parts_total} 个元件")
            for pn in panels:
                pan_id = pn.get("panel_id", "?")
                pn_parts = pn.get("parts", [])
                lines.append(f"      面板 [{pan_id}] {pn.get('panel_type', '?')} — {len(pn_parts)} 个元件")
                for pt in pn_parts:
                    lines.append(f"        元件 [{pt.get('part_id', '?')}] {pt.get('part_type', '?')} {pt.get('part_model', '')}")
        return "\n".join(lines)

    return [add_cabinets, add_panels, add_parts, edit_cabinet, edit_panel, edit_part,
            delete_cabinet, delete_panel, delete_part, get_current_selection, get_schema_summary]


# ──────────────────────────────────────────────────────────────
#  构建 LangGraph ReAct 图
# ──────────────────────────────────────────────────────────────

def build_agent(domain=None, checkpointer: InMemorySaver | None = None):
    """构建并编译 LangGraph ReAct Agent。domain 用于动态获取字段定义和选项。"""
    if domain is None:
        raise ValueError("domain 参数不能为空，请传入 BusinessDomain 实例")

    ui_schema = domain.ui_schema()
    part_types = domain.get_part_types()

    models = _build_input_models(ui_schema, part_types)
    tools = _build_tools(models)
    system_prompt = _build_system_prompt(ui_schema, part_types)

    llm = _build_llm()
    llm_with_tools = llm.bind_tools(tools)

    async def call_model(state: AgentState) -> dict:
        msgs = state["messages"]
        if not msgs or not isinstance(msgs[0], SystemMessage):
            msgs = [SystemMessage(content=system_prompt)] + list(msgs)
        response = await llm_with_tools.ainvoke(msgs)
        return {"messages": [response]}

    def should_continue(state: AgentState) -> str:
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None):
            return "tools"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", should_continue, ["tools", END])
    graph.add_edge("tools", "agent")
    return graph.compile(checkpointer=checkpointer or _agent_checkpointer)


_agent_instance = None


def get_agent(domain=None):
    global _agent_instance
    if _agent_instance is None:
        _agent_instance = build_agent(domain=domain)
    return _agent_instance
