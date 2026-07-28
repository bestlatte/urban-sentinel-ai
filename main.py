"""FastAPI 入口：四個 REST 端點 + /ws + 掛載 frontend/ 靜態檔（單一 Server）。

參考 spec：`.kiro/specs/m5-api-orchestrator-dashboard/design.md` 第3節「main.py：端點與payload對應」；
固定 API 表面見 `.kiro/steering/00-tech-stack.md` §4，**不得擴充端點**。

`POST /api/what-if` 依問題類型回傳 `WhatIfResult` 或 `TraceAnswer`，見
`.kiro/steering/04-system-architecture.md` §5 三分支路由規則，不要誤以為這個
端點永遠回傳同一種形狀。
"""

from __future__ import annotations

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from src import orchestrator
from src.ws_manager import ConnectionManager

app = FastAPI()
ws_manager = ConnectionManager()

# [2026-07-28總架構師補充：架構完整性修正] 原本這裡寫 `GATEWAY = build_gateway()`
# 建立的是 main.py 自己的區域變數，跟 `src/orchestrator.py` 模組層級的 `GATEWAY`
# （orchestrator.py 內的函式實際讀取的那個）是兩個不同的名字空間——orchestrator.py
# 的 handle_incident/handle_trigger_batch 永遠只會看到 None。改成直接賦值給
# orchestrator 模組本身，確保只有一份 GATEWAY 實例。
orchestrator.GATEWAY = orchestrator.build_gateway()

# frontend/ 以 StaticFiles(html=True) 掛在 /，API 前綴 /api 與 /ws 不會被靜態路由吃掉。
app.mount("/frontend", StaticFiles(directory="frontend", html=True), name="frontend")


@app.exception_handler(Exception)
async def unified_exception_handler(request: Request, exc: Exception):
    """三個 Envelope 端點共用一個例外處理器（m5-api-orchestrator-dashboard/design.md
    第3節），把例外收斂成 status="error" 的 Envelope。[2026-07-28總架構師補充：
    架構完整性修正] 這個處理器原本設計文件裡提到了，但鷹架第一版沒有真的接上，
    是「文件說有、程式碼沒有」的落差，這裡補上骨架。

    TODO(Kiro): ValidationError→VALIDATION_ERROR（errors[0].field標明失敗欄位）；
    ValueError（DATA_NOT_FOUND情境，如 event_id 不存在）→ DATA_NOT_FOUND；
    asyncio.TimeoutError→TIMEOUT；下游模組自行拋出的具名錯誤原碼透傳；
    其餘未預期例外→INTERNAL_ERROR。一律用 build_envelope() 組裝回應，不是這裡的
    佔位 dict。GET /api/health 不套用此處理器（不使用Envelope）。
    """
    if isinstance(exc, ValidationError):
        code = "VALIDATION_ERROR"
    else:
        code = "INTERNAL_ERROR"
    return JSONResponse(
        status_code=200,
        content={"status": "error", "errors": [{"code": code, "message": str(exc)}]},
    )


@app.get("/api/dashboard")
async def get_dashboard():
    """TODO(Kiro): 回傳 message_type=dashboard.updated.v1 的 Envelope(DashboardPayload)。"""
    raise NotImplementedError("見 m5-api-orchestrator-dashboard/design.md 第3節")


@app.post("/api/incidents/evaluate")
async def evaluate_incident(body: dict):
    """TODO(Kiro): body={"event_id": str}；event_id 不存在於 NormalizedDataBundle.incidents
    時回 DATA_NOT_FOUND；呼叫 handle_incident()，回傳 decision.completed.v1 Envelope，
    並 broadcast 同一份內容 + dashboard.updated.v1。
    """
    raise NotImplementedError("見 m5-api-orchestrator-dashboard/design.md 第3-4節")


@app.post("/api/what-if")
async def what_if(body: dict):
    """TODO(Kiro): body 對應 WhatIfRequest（見 src/models.py）。呼叫
    handle_user_query(question, current_trace_id)，依三分支路由回傳對應 Envelope
    （whatif.evaluated.v1／WhatIfResult 或 trace.answered.v1／TraceAnswer，
    見 04-system-architecture.md §5）。
    scenario_overrides 為空且問題判定為前瞻假設分支時回 VALIDATION_ERROR。
    """
    raise NotImplementedError("見 SPEC-O3 §4 + m5-api-orchestrator-dashboard/requirements.md R2.5/R2.5a")


@app.get("/api/health")
async def health():
    """不使用 Envelope（此端點不套用上方的統一例外處理器邏輯）。
    TODO(Kiro): 回傳 {status, use_bedrock, gateway_mode}；gateway_mode 依
    `orchestrator.GATEWAY` 是 StubGateway/LiveGateway/混合 回傳 stub/live/mixed。
    """
    raise NotImplementedError("見 m5-api-orchestrator-dashboard/design.md 第3節")


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """單向：receive_text() 只為偵測斷線，收到的內容丟棄
    （F6 的 chat.clear_session.v1 例外會真的處理，見 W2-session-manager/design.md 第五節）。
    """
    await ws_manager.connect(websocket)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)
