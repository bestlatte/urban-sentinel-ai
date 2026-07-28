# W1 — What-if 問答 Agent | Design

> 前置文件：`specs/W1-whatif-agent/requirements.md`
> 本文件定義 W1 的技術實作方式。W1 是四個元件中最複雜的，因為它整合了意圖判斷、工具呼叫、回覆格式化。

> **[2026-07-28 總架構師補註] 進場方式改為由 Orchestrator 轉發，非 W1 自己接 WebSocket**
>
> `m4-explanation-chain-and-orchestrator/SPEC-O3_Orchestrator_對外介面.md` §4 明訂：使用者輸入路由是**確定性、零 LLM**的，入口是 `handle_user_query(question, current_trace_id) -> AnswerText`（對應 `POST /api/what-if`，`00-tech-stack.md` §4 固定端點；SPEC-O3 原文寫 `/api/chat` 是筆誤，端點以 `00-tech-stack.md` 為準）。Orchestrator 判斷問題含前瞻假設詞（「如果」「假設」「若」等）才轉發給 W1；不是 W1 自己接 WebSocket 訊息、由內部 Agent 自己判斷要不要處理。
>
> 這跟原本第六、九、十節寫的「WebSocket handler 直接呼叫 `process_whatif()`」方向相反，也跟 `00-tech-stack.md` §4「所有改變狀態的操作走 REST；POST 必須同步回傳完整結果，WebSocket 只是額外通知」的規則衝突（原設計把使用者的問題本身當成 WebSocket 訊息送出）。已對齊修正：
> - 對外入口改為 `POST /api/what-if`，同步回傳完整 `W1Response`；WebSocket 只用來推播 loading 步驟等**額外通知**，不是問題本身的傳輸管道。
> - `process_whatif()` 由 `orchestrator.handle_user_query()` 呼叫，不是 W1 自己接 WebSocket。
> - W1 內部「LLM 自動決定要不要呼叫 `query_sop`／`simulate_scenario`」的設計本身不變——那是 W1 收到問題**之後**的內部邏輯，跟「誰先判斷這是不是 What-if 問題」是兩件事，不衝突。
>
> 另外三個機械性修正：`src.rag.sop_retriever` → `src.bedrock_service.sop_retriever`（K3 檔案結構已改名）；`result.source` → `result.retrieval_source`（K3 欄位已改名）；Bedrock model ID 從硬編碼改為讀 `BEDROCK_MODEL_ID` 環境變數（跟本文件 `tasks.md` 原本就寫的「model ID 從環境變數讀取」對齊，原本這裡的程式碼碼跟自己的 tasks.md 不一致）。
>
> `simulate_scenario` 這個 tool 內部呼叫的對象也需要修正：原寫 `from src.orchestrator import simulate`，但 SPEC-O1/O2/O3 都沒有定義這個函式——而且 Orchestrator 呼叫 W1、W1 又反過來呼叫 Orchestrator 會形成循環依賴。
>
> **[2026-07-28再更正，鷹架階段定案]** 不是「直接呼叫 `routing.py`/`rules.py`/`reporting.py`」，而是透過 `src/whatif_engine.run_scenario()` 這個新增的膠合層，並且**經由 `orchestrator.GATEWAY`**（`ModuleGateway` 實例，不是 `orchestrator.py` 的函式）呼叫 `evaluate_rules`/`plan_routes`/`calculate_ete`——理由是維持 Stub/Live 切換機制在整個系統內一致，不要讓 What-if 這條路徑繞過 `ModuleGateway`、變成唯一一個直接 import 決定性模組的例外。`apply_scenario_overrides()`（覆寫 bundle）與 `run_scenario()` 已在 `src/whatif_engine.py` 鷹架完成，函式簽章已定案，`_get_current_context()`（目前作用中的 incident/bundle 從哪裡取得）仍是待補的整合點。

---

## 一、架構總覽

```
W2 交出 W1Context
       │
       ▼
┌──────────────────────────────────────────────┐
│                W1 模組                        │
│                                              │
│  Strands Agent（LLM 大腦）                    │
│    ├─ System Prompt（角色定義 + 規則約束）     │
│    ├─ @tool query_sop()       → K3           │
│    ├─ @tool simulate_scenario() → A2         │
│    └─ LLM 自行處理（閒聊、組合回答）          │
│                                              │
│  回覆格式化器                                 │
│    └─ 把 Agent 輸出轉成 W1Response            │
└──────────────────────────────────────────────┘
       │
       ▼
W1Response（結構化 JSON + 自然語言摘要）
```

W1 本質上就是一個 Strands Agent，配備 2 個 tool + 一段 system prompt。LLM 自己決定要不要呼叫 tool。

---

## 二、核心設計決策

### 為什麼用 Strands Agent 而不是自己寫 if/else 判斷意圖？

- Strands Agent 的 LLM 會自動根據問題決定「要不要 call tool」。
- 如果問題是閒聊 → LLM 直接回答，不 call tool。
- 如果問題跟 SOP 有關 → LLM 自動 call `query_sop`。
- 如果問題是 what-if → LLM 自動 call `query_sop` + `simulate_scenario`。

我們不需要自己寫意圖分類器，**LLM + 好的 system prompt** 就能做到。

---

## 三、System Prompt

```python
SYSTEM_PROMPT = """你是「交通策略諮詢顧問」，部署在台北市信義區智慧交通指揮中心的 Dashboard 上。

## 你的角色
- 回答指揮官與評審的假設性問題（What-if）
- 精準引用 SOP 條款，不編造
- 呼叫工具取得事實，不自行推算數字

## 嚴格規則
1. SOP 條款內容：只能引用 query_sop 工具回傳的原文，不可自行編寫條款。
2. 路線/ETE/級別：只能引用 simulate_scenario 工具回傳的計算結果，不可自行計算。
3. 如果 query_sop 回傳空結果，明確告知使用者「SOP 未涵蓋此情境」。
4. 如果 simulate_scenario 不可用（回傳錯誤），退化為「基於 SOP 條款推估」，並標示為推估。

## 回覆風格
- 先用一句話說結論
- 再展開細節（觸發條款、依據、動作、路網影響、ETE）
- 最後提供 3 個延伸問題啟發使用者
- 語氣專業但親切，像一位資深交通顧問

## 處理非交通問題
- 禮貌拒絕：「我是交通策略諮詢顧問，目前只能回答交通應變相關的問題。請問有什麼交通方面想了解的嗎？」
- 仍提供 3 個預設延伸問題引導回正題

## 處理 SOP 邊界問題
- 如果問題與交通相關但 SOP 未明文涵蓋，可基於現有條款做合理推測
- 但必須明確標示「以下為基於現有 SOP 的推測，非明文規定」

## 對話上下文
- 使用者可能做累積假設（「如果 A…」→「那再加上 B 呢？」）
- 回答時把所有累積假設考慮進去
- 引用當前即時數據讓回答有時效感
"""
```

---

## 四、Tool 定義

### 4.1 query_sop（呼叫 K3）

```python
from strands import tool

@tool
def query_sop(question: str) -> dict:
    """查詢 SOP 條款。輸入自然語言問題，回傳最相關的 SOP 條款原文。
    
    何時使用：
    - 使用者問 SOP 規則內容
    - 需要確認某個情境會觸發哪條 SOP
    - What-if 問題中需要引用條款依據
    """
    from src.bedrock_service.sop_retriever import query_sop as _query
    result = _query(question)
    return {
        "sections": [
            {
                "section_number": s.section_number,
                "title": s.title,
                "content": s.content,
                "relevance_score": s.relevance_score
            }
            for s in result.sections
        ],
        "retrieval_source": result.retrieval_source
    }
```

### 4.2 simulate_scenario（呼叫 A2）

```python
@tool
def simulate_scenario(assumptions: dict, question: str) -> dict:
    """用假設參數模擬交通情境。呼叫決策模組重新計算路線、ETE、觸發條款。
    
    何時使用：
    - 使用者提出 What-if 假設（例如「如果人數到 40000」）
    - 需要精確的路線計算或 ETE 數值
    
    Args:
        assumptions: 假設參數，格式為 {"entity.field": value}
                     例如 {"BS_MRT_BL17.User_Count": 40000, "RD_TPE_002.status": "Closed"}
        question: 使用者的原始問題（供 A2 理解上下文）
    
    Returns:
        模擬計算結果，包含觸發條款、路線建議、ETE 等
    """
    # [2026-07-28鷹架階段定案] 透過 whatif_engine.run_scenario() + orchestrator.GATEWAY，
    # 見本檔頭部補註；不經過 orchestrator.py 的函式本身（避免 Orchestrator→W1→Orchestrator 循環依賴），
    # 但經由它持有的 GATEWAY 實例存取 M1/M2/M4，維持 Stub/Live 切換機制一致。
    try:
        from src import orchestrator
        from src.whatif_engine import run_scenario

        incident, bundle = _get_current_context()  # 待補：目前作用中事件從哪取得
        result = run_scenario(bundle, incident, assumptions, orchestrator.GATEWAY)
        return result
    except (ImportError, Exception) as e:
        return {
            "status": "unavailable",
            "message": f"決策模組暫時不可用：{str(e)}",
            "fallback": True
        }
```

---

## 五、Agent 建立

```python
from strands import Agent

def create_whatif_agent() -> Agent:
    """建立 W1 Agent 實例"""
    import os
    return Agent(
        model=os.environ["BEDROCK_MODEL_ID"],  # 唯一來源見 00-tech-stack.md §5 .env.example
        tools=[query_sop, simulate_scenario],
        system_prompt=SYSTEM_PROMPT,
    )

# 全域 Agent 實例（重複使用，不每次 request 重建）
WHATIF_AGENT = create_whatif_agent()
```

---

## 六、主處理流程

```python
from src.session.models import W1Context

def process_whatif(context: W1Context) -> W1Response:
    """
    W1 的主入口。接收 W2 整理好的上下文，回傳結構化回覆。
    """
    # 1. 組合 prompt（上下文 + 使用者訊息）
    prompt = _build_prompt(context)
    
    # 2. 呼叫 Agent（LLM 自動判斷意圖 + 選工具）
    raw_response = WHATIF_AGENT(prompt)
    
    # 3. 格式化回覆
    response = _format_response(raw_response, context)
    
    return response


def _build_prompt(context: W1Context) -> str:
    """把 W1Context 組合成一段 prompt 給 Agent"""
    parts = []
    
    # 對話歷史
    if context.history:
        parts.append("=== 對話歷史 ===")
        for turn in context.history:
            parts.append(f"使用者：{turn.user_message}")
            parts.append(f"顧問：{turn.ai_response}")
        parts.append("")
    
    # 累積假設
    if context.accumulated_assumptions:
        parts.append("=== 目前累積的假設條件 ===")
        for key, value in context.accumulated_assumptions.items():
            parts.append(f"- {key} = {value}")
        parts.append("")
    
    # 本次訊息
    parts.append(f"使用者新問題：{context.new_message}")
    
    return "\n".join(parts)
```

---

## 七、回覆資料結構

### W1Response（W1 回傳給 API 的最終格式）

```python
@dataclass
class W1Response:
    # 意圖分類
    intent_type: str              # "chitchat" | "sop_query" | "whatif_simulation"
    
    # 自然語言摘要（給對話氣泡用）
    summary: str
    
    # 結構化資料（給 Decision Card 用，部分欄位 may be None）
    triggered_sops: list[dict]    # [{"section_number": 3, "title": "...", "content": "..."}]
    judgment_basis: str | None    # 判定依據文字
    expected_actions: list[str]   # ["建議北捷過站不停", "通知公車處..."]
    route_impact: dict | None     # {"blocked": [...], "primary": "...", "secondary": "..."}
    ete: dict | None              # {"minutes": 89, "formula": "60 + (0.99-0.5)*60", "recovery_time": "23:40"}
    current_data: dict | None     # 引用的當前數據 snapshot
    
    # 延伸問題
    suggested_questions: list[str]  # 3 個延伸問題
    
    # 元資訊
    source_mode: str              # "full"（A2 可用）| "degraded"（A2 不可用，僅 K3）
    tools_called: list[str]       # ["query_sop", "simulate_scenario"] 或 ["query_sop"] 或 []
```

### 不同意圖的欄位使用

| 意圖 | 哪些欄位有值 |
|------|------------|
| chitchat | `summary`, `suggested_questions`，其餘為 None/空 |
| sop_query | `summary`, `triggered_sops`, `suggested_questions` |
| whatif_simulation | 全部欄位都有值（A2 可用時）|

---

## 八、回覆格式化

Agent 的原始回覆是自然語言文字。需要一個格式化步驟把它轉成 `W1Response`：

```python
def _format_response(raw_response, context: W1Context) -> W1Response:
    """
    解析 Agent 的回覆，結合 tool 呼叫結果，組成 W1Response。
    
    策略：
    - Agent 的 tool 呼叫記錄中能取得 query_sop / simulate_scenario 的回傳值
    - 用這些結構化資料填入 W1Response 的對應欄位
    - Agent 的最終文字回覆作為 summary
    - 延伸問題從 Agent 回覆中解析（Agent 被 prompt 要求生成 3 個）
    """
    # 從 Agent trace 取得 tool call results
    tool_results = _extract_tool_results(raw_response)
    
    # 判斷意圖（根據呼叫了哪些 tool）
    tools_called = list(tool_results.keys())
    if not tools_called:
        intent_type = "chitchat"
    elif "simulate_scenario" in tools_called:
        intent_type = "whatif_simulation"
    else:
        intent_type = "sop_query"
    
    # 從 tool results 填入結構化欄位
    triggered_sops = []
    if "query_sop" in tool_results:
        triggered_sops = tool_results["query_sop"].get("sections", [])
    
    simulation = tool_results.get("simulate_scenario", {})
    
    # 解析延伸問題（從 Agent 回覆文字中提取）
    suggested_questions = _extract_suggested_questions(str(raw_response))
    
    return W1Response(
        intent_type=intent_type,
        summary=_extract_summary(str(raw_response)),
        triggered_sops=triggered_sops,
        judgment_basis=simulation.get("judgment_basis"),
        expected_actions=simulation.get("actions", []),
        route_impact=simulation.get("route_impact"),
        ete=simulation.get("ete"),
        current_data=simulation.get("current_data_snapshot"),
        suggested_questions=suggested_questions,
        source_mode="full" if simulation and not simulation.get("fallback") else "degraded",
        tools_called=tools_called
    )
```

---

## 九、退化模式（A2 不可用時）

當 `simulate_scenario` 回傳 `{"status": "unavailable", "fallback": True}` 時：

1. W1 的 Agent 會看到 tool 回傳了 "unavailable"
2. System prompt 裡的規則 #4 指示 Agent：退化為「基於 SOP 條款推估」
3. Agent 會用 `query_sop` 取得的條款原文，自己推理可能的結果
4. 回覆中會明確標示「以下為基於 SOP 條款的推估，非精確計算」
5. `source_mode` 設為 `"degraded"`
6. `ete`、`route_impact` 等精確計算欄位為 None

這讓你在 A2 還沒做好之前就能 Demo 完整的對話流程。

---

## 十、API 整合（由 Orchestrator 呼叫，非 W1 自接 WebSocket）

`POST /api/what-if` 是唯一對外入口（`00-tech-stack.md` §4 固定端點）。`main.py` 收到請求後交給
`orchestrator.handle_user_query(question, current_trace_id)`；Orchestrator 判斷是 What-if 問題後才呼叫本節的
`process_whatif_request()`。POST 必須同步回傳完整 `W1Response`；WebSocket 只用來推播 loading 進度，屬於
額外通知，不是問題本身的傳輸管道（見 `chat.loading_step.v1` 等 Envelope 訊息，格式對齊 `F6-chat-ui/design.md`）。

```python
# 由 orchestrator.handle_user_query() 呼叫，不是 W1 自己接 WebSocket

def process_whatif_request(session_id: str, content: str, ws_broadcaster=None) -> "W1Response":
    from src.session.session_manager import handle_message, record_response
    from src.agent.whatif_agent import process_whatif
    
    # 1. W2 組上下文
    context = handle_message(session_id, content)
    
    # 2. 推播 loading 步驟（額外通知，不影響同步回傳；ws_broadcaster 不可用時直接跳過）
    if ws_broadcaster:
        ws_broadcaster.send("chat.loading_step.v1", {"step": "解析問題意圖", "status": "active"})
    
    # 3. W1 處理（內部會呼叫 tool）
    response = process_whatif(context)
    
    # 4. W2 記錄回覆
    record_response(
        session_id=session_id,
        ai_response=response.summary,
        triggered_sops=[s["section_number"] for s in response.triggered_sops],
        new_assumptions=_extract_new_assumptions(response)  # 從模擬結果中提取
    )
    
    # 5. 同步回傳給 orchestrator，由 orchestrator 組進 POST /api/what-if 的回應
    return response
```

---

## 十一、Loading 步驟推播

W1 處理過程中，透過 WebSocket 逐步推送進度：

```python
LOADING_STEPS = [
    "解析問題意圖",
    "檢索 SOP 條款",
    "呼叫決策模組",
    "計算 ETE",
    "組合回覆"
]
```

實際推播時機：
- Agent 開始 → 推 step 1 "active"
- Agent call `query_sop` → 推 step 1 "done" + step 2 "active"
- Agent call `simulate_scenario` → 推 step 2 "done" + step 3 "active"
- simulate 完成 → 推 step 3 "done" + step 4 "active"（或跳過）
- 最終回覆 → 推全部 "done"

> 注意：Strands Agent 目前不支援 streaming tool call 事件。實作時可能需要用 callback 或在 tool function 內主動推播。若做不到逐步推播，退化為「開始 loading → 全部完成」兩段式即可。

---

## 十二、錯誤處理

| 情境 | 處理方式 |
|------|---------|
| LLM 呼叫失敗（Bedrock timeout） | 回覆「系統暫時忙碌，請稍後再試」，`intent_type = "error"` |
| `query_sop` 失敗 | Agent 繼續嘗試回答，但標示「SOP 檢索暫時不可用」 |
| `simulate_scenario` 失敗 | 退化模式（見第九節） |
| Agent 回覆中缺少延伸問題 | 使用預設問題填充（見下方） |

### 預設延伸問題（fallback）

```python
DEFAULT_QUESTIONS = [
    "目前系統是什麼應變等級？",
    "替代路線還有容量嗎？",
    "ETE 預計多久恢復？"
]
```

---

## 十三、檔案結構（預期）

```
src/
└── agent/
    ├── __init__.py
    ├── whatif_agent.py       # create_whatif_agent(), process_whatif() 主邏輯
    ├── system_prompt.py      # SYSTEM_PROMPT 常數
    ├── tools.py              # @tool query_sop, @tool simulate_scenario
    ├── response_formatter.py # _format_response(), W1Response 定義
    └── loading.py            # loading 步驟推播邏輯
```
