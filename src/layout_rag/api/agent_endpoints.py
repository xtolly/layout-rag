"""
配置智能体 API 路由

POST /api/agent/chat/stream  — SSE 流式（token 级）
POST /api/agent/chat         — 非流式备用
POST /api/agent/config       — 运行时设置 API Key
GET  /api/agent/status       — 获取 Agent 状态
"""
from __future__ import annotations

import json
import os
import traceback
import uuid
from typing import Any

from fastapi import APIRouter, Body
from fastapi.responses import StreamingResponse
from langchain_core.messages import HumanMessage

agent_router = APIRouter(prefix="/agent")


def _get_agent():
    from layout_rag.agent.configurator_agent import get_agent
    return get_agent()


def _sse(data: Any) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


def _resolve_session_id(payload: dict) -> str:
    session_id = str(payload.get("session_id", "") or "").strip()
    return session_id or str(uuid.uuid4())


def _agent_run_config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


# ──────────────────────────────────────────────────────────────
#  SSE 流式接口（astream_events — token 级流式）
# ──────────────────────────────────────────────────────────────
@agent_router.post("/chat/stream")
async def chat_stream(payload: dict = Body(...)):
    """
    SSE 协议，事件类型：
      {"type": "token",  "content": "..."}    — LLM 生成的文字片段
      {"type": "action", "action": {...}}      — 工具执行结果（含 message 字段）
      {"type": "thinking","content": "..."}    — （可选）思考过程摘要
      {"type": "done"}                         — 流结束
      {"type": "error",  "message": "..."}     — 发生错误
    """
    message = payload.get("message", "")
    scheme  = payload.get("scheme", {"cabinets": []})
    image   = payload.get("image")          # base64 data-url 或 None
    selection = payload.get("selection", {})  # {cabinet_id, panel_id}
    session_id = _resolve_session_id(payload)

    async def event_stream():
        try:
            agent = _get_agent()

            # 写入选中状态 & 当前方案，供工具读取
            from layout_rag.agent.configurator_agent import set_current_selection, set_current_scheme
            set_current_selection(selection)
            set_current_scheme(scheme)

            # 构造消息内容：纯文本 / 图文混合（OpenAI Vision 格式）
            msg_text = (message or '请根据图片生成配置方案') if image else message

            if image:
                content_parts: list[dict] = []
                if msg_text:
                    content_parts.append({"type": "text", "text": msg_text})
                content_parts.append({
                    "type": "image_url",
                    "image_url": {"url": image},
                })
                human_msg = HumanMessage(content=content_parts)
            else:
                human_msg = HumanMessage(content=msg_text)

            init_state = {
                "messages": [human_msg],
                "current_scheme": scheme,
            }

            # astream_events 可拿到 token 级 on_chat_model_stream 事件
            async for event in agent.astream_events(
                init_state,
                config=_agent_run_config(session_id),
                version="v2",
            ):
                kind = event.get("event", "")

                # ── Token 级流式（LLM 输出） ──────────────────────
                if kind == "on_chat_model_stream":
                    chunk = event.get("data", {}).get("chunk")
                    if chunk is None:
                        continue
                    # 尝试多种方式获取 reasoning_content（兼容不同版本的 langchain 封装）
                    reasoning = ""
                    if hasattr(chunk, "additional_kwargs"):
                        reasoning = chunk.additional_kwargs.get("reasoning_content", "")
                    if not reasoning and hasattr(chunk, "response_metadata"):
                        reasoning = chunk.response_metadata.get("reasoning_content", "")
                    
                    if reasoning:
                        yield _sse({"type": "thinking", "content": reasoning})

                    content = getattr(chunk, "content", "") or ""
                    # 只要有内容，不管有没有 tool_calls，全部当做普通的文字片段推出去
                    if content:
                        yield _sse({"type": "token", "content": content})

                # ── 工具执行结束（拿到工具返回值） ────────────────
                elif kind == "on_tool_end":
                    raw_output = event.get("data", {}).get("output", "")
                    # output 可能是字符串或 ToolMessage
                    if hasattr(raw_output, "content"):
                        raw_output = raw_output.content
                    try:
                        action_data = json.loads(str(raw_output))
                        yield _sse({"type": "action", "action": action_data})
                    except Exception:
                        # 非 JSON 工具输出，作为提示推送
                        yield _sse({"type": "action", "action": {
                            "action": "info",
                            "message": str(raw_output)[:200],
                        }})

            yield _sse({"type": "done"})

        except Exception as e:
            traceback.print_exc()
            yield _sse({"type": "error", "message": str(e)})

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ──────────────────────────────────────────────────────────────
#  非流式接口（备用）
# ──────────────────────────────────────────────────────────────
@agent_router.post("/chat")
async def chat(payload: dict = Body(...)):
    message = payload.get("message", "")
    scheme  = payload.get("scheme", {"cabinets": []})
    image   = payload.get("image")
    selection = payload.get("selection", {})
    session_id = _resolve_session_id(payload)
    try:
        agent = _get_agent()

        from layout_rag.agent.configurator_agent import set_current_selection, set_current_scheme
        set_current_selection(selection)
        set_current_scheme(scheme)

        msg_text = message
        if image:
            content_parts: list[dict] = []
            if msg_text:
                content_parts.append({"type": "text", "text": msg_text})
            content_parts.append({"type": "image_url", "image_url": {"url": image}})
            human_msg = HumanMessage(content=content_parts)
        else:
            human_msg = HumanMessage(content=msg_text)
        result = agent.invoke(
            {
                "messages": [human_msg],
                "current_scheme": scheme,
            },
            config=_agent_run_config(session_id),
        )
        last = result["messages"][-1]
        reply = getattr(last, "content", str(last))
        actions = _extract_tool_actions(result["messages"])
        return {"reply": reply, "actions": actions, "session_id": session_id}
    except Exception as e:
        traceback.print_exc()
        return {"reply": f"Agent 出错：{e}", "actions": [], "session_id": session_id}


@agent_router.get("/status")
async def agent_status():
    has_key = os.getenv("OPENAI_API_KEY", "")
    model_name = os.getenv("MODEL_NAME", "")
    base_url = os.getenv("OPENAI_API_BASE", "")
    return {
        "ready": bool(has_key),
        "model": model_name,
        "base_url": base_url,
        "has_api_key": bool(has_key),
    }


# ──────────────────────────────────────────────────────────────
#  内部辅助
# ──────────────────────────────────────────────────────────────
def _extract_tool_actions(messages: list) -> list[dict]:
    from langchain_core.messages import ToolMessage
    actions = []
    for msg in messages:
        if isinstance(msg, ToolMessage):
            try:
                actions.append(json.loads(msg.content))
            except Exception:
                pass
    return actions
