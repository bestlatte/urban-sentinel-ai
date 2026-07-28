"""F6 前端獨立開發用的簡易 mock server，不是應用程式的一部分（見
`.kiro/steering/00-tech-stack.md` §3 `scripts/` 的定位——純開發期間驗證用，
Demo 前刪除或忽略即可，不算「新增模組檔」）。

參考 spec：`.kiro/specs/m3-bedrock-advisor/F6-chat-ui/tasks.md` Task 11
（已修正版：使用者訊息走 `POST /api/what-if`，不是 WebSocket `chat_message`；
`/ws` 只推播 loading 進度）。

用法：`python3 scripts/mock_server.py`，接著用瀏覽器開 F6 前端，`sendMessage()`
打到這裡的 `POST /api/what-if` 會拿到固定的 mock `WhatIfResult`。
"""

from __future__ import annotations

import asyncio

from fastapi import FastAPI, WebSocket
from fastapi.responses import JSONResponse

app = FastAPI()


@app.post("/api/what-if")
async def mock_what_if(body: dict):
    """TODO(Kiro): 收到任何請求 → 等 2 秒（模擬處理時間）→ 回傳一個完整的
    mock Envelope(message_type="whatif.evaluated.v1", payload=WhatIfResult固定值)。
    """
    await asyncio.sleep(2)
    raise NotImplementedError("見 F6-chat-ui/tasks.md Task 11：填入固定 mock WhatIfResult")


@app.websocket("/ws")
async def mock_ws(websocket: WebSocket):
    """TODO(Kiro): 連線後推播固定的 chat.loading_step.v1 序列
    （「解析問題意圖」→「檢索SOP條款」→...），模擬 F6 的 loading 步驟動畫。
    """
    await websocket.accept()
    raise NotImplementedError("見 F6-chat-ui/tasks.md Task 11")


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=8001)
