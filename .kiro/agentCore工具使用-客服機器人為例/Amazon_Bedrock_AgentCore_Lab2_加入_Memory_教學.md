# Amazon Bedrock AgentCore Lab 2：替 Agent 加入 Memory

## 0. 本 Lab 要完成什麼？

在 Lab 1 中建立的 Customer Support Agent，每次對話都從零開始，無法記住：

- 使用者姓名
- 個人偏好
- 曾購買的商品
- 過去發生過的問題
- 前一次對話內容

本 Lab 會加入 **Amazon Bedrock AgentCore Memory**，讓 Agent 能跨 Session 記住使用者資訊。

完成後，Agent 可以做到：

```text
第一次對話：
「我叫 Sarah，我偏好 Email 通知，最近買了一支 Smart Watch。」

隔一段時間、換一個 Session 再問：
「你知道我的哪些資訊？」

Agent 回答：
「你的名字是 Sarah、偏好 Email 通知，而且最近買了 Smart Watch。」
```

---

# 1. 先理解 AgentCore Memory

AgentCore Memory 在本 Lab 使用兩種策略：

| Strategy | 用途 | 內容 |
|---|---|---|
| `SEMANTIC` | 保存事實與偏好 | 姓名、喜好、訂單、個人資訊 |
| `SUMMARIZATION` | 保存對話摘要 | 將一段對話壓縮成摘要，供後續接續 |

本 Lab 使用的 Namespace：

```text
/users/{actorId}/facts
```

保存特定使用者的語意事實。

```text
/summaries/{actorId}/{sessionId}
```

保存特定使用者、特定 Session 的對話摘要。

---

# 2. 前置條件

開始前請確認：

- 已完成 Lab 1
- `CustomerSupport` 專案可以正常執行
- 已安裝 AgentCore CLI
- AWS Credential 仍然有效
- 已部署過 Lab 1 的 Agent
- Terminal 目前位於 `CustomerSupport` 專案根目錄

如果 Lab 1 的本機伺服器還在執行，先停止：

### Interactive TUI

```text
Esc
```

### Logs Mode

```text
Ctrl + C
```

---

# 3. Step 1：加入 Memory Resource

在 Kiro Terminal 執行：

```powershell
agentcore add memory `
  --name SharedMemory `
  --strategies "SEMANTIC,SUMMARIZATION" `
  --expiry 30
```

也可以寫成單行：

```powershell
agentcore add memory --name SharedMemory --strategies "SEMANTIC,SUMMARIZATION" --expiry 30
```

參數說明：

| 參數 | 意義 |
|---|---|
| `--name SharedMemory` | Memory Resource 名稱 |
| `--strategies` | 啟用 Semantic 與 Summarization |
| `--expiry 30` | Memory 保存期限設定為 30 天 |

成功後應看到：

```text
Added memory 'SharedMemory'
```

---

# 4. Step 2：確認 `agentcore.json`

執行：

```powershell
Get-Content agentcore\agentcore.json
```

確認 `memories` 陣列已加入 `SharedMemory`。

AgentCore CLI 會自動：

1. 更新 `agentcore/agentcore.json`
2. 加入 Memory Resource
3. 設定 `SEMANTIC`
4. 設定 `SUMMARIZATION`
5. 建立對應 Namespace Pattern

> 此時只是更新本機設定，Memory 還沒有真的建立到 AWS。

---

# 5. Step 3：建立 Memory 模組

在 Terminal 執行：

```powershell
mkdir app\CustomerSupport\memory
New-Item app\CustomerSupport\memory\__init__.py -Force
New-Item app\CustomerSupport\memory\session.py -Force
```

建立完成後，目錄會變成：

```text
app/
└── CustomerSupport/
    ├── main.py
    ├── memory/
    │   ├── __init__.py
    │   └── session.py
    ├── model/
    ├── mcp_client/
    └── pyproject.toml
```

---

# 6. Step 4：撰寫 `memory/session.py`

開啟：

```text
app/CustomerSupport/memory/session.py
```

貼入以下程式碼：

```python
import os
from typing import Optional

from bedrock_agentcore.memory.integrations.strands.config import (
    AgentCoreMemoryConfig,
    RetrievalConfig,
)
from bedrock_agentcore.memory.integrations.strands.session_manager import (
    AgentCoreMemorySessionManager,
)


MEMORY_ID = os.getenv("MEMORY_SHAREDMEMORY_ID")
REGION = os.getenv("AWS_REGION")


def get_memory_session_manager(
    session_id: str,
    actor_id: str,
) -> Optional[AgentCoreMemorySessionManager]:
    """建立特定使用者與 Session 的 Memory Session Manager."""

    if not MEMORY_ID:
        return None

    retrieval_config = {
        f"/users/{actor_id}/facts": RetrievalConfig(
            top_k=3,
            relevance_score=0.3,
        ),
        f"/summaries/{actor_id}/{session_id}": RetrievalConfig(
            top_k=3,
            relevance_score=0.3,
        ),
    }

    return AgentCoreMemorySessionManager(
        AgentCoreMemoryConfig(
            memory_id=MEMORY_ID,
            session_id=session_id,
            actor_id=actor_id,
            retrieval_config=retrieval_config,
        ),
        REGION,
    )
```

---

## 6.1 這段程式做什麼？

### 讀取 Memory ID

```python
MEMORY_ID = os.getenv("MEMORY_SHAREDMEMORY_ID")
```

部署後，AgentCore Runtime 會自動注入：

```text
MEMORY_SHAREDMEMORY_ID
```

這個環境變數會保存實際建立的 Memory Resource ID。

---

### 讀取 AWS Region

```python
REGION = os.getenv("AWS_REGION")
```

Memory Client 需要知道要連接哪一個 AWS Region。

---

### 建立 User Facts Namespace

```python
f"/users/{actor_id}/facts"
```

用來保存：

- 使用者名稱
- 偏好
- 購買資訊
- 其他可抽取的事實

---

### 建立 Session Summary Namespace

```python
f"/summaries/{actor_id}/{session_id}"
```

用來保存特定 Session 的對話摘要。

---

### 設定檢索參數

```python
RetrievalConfig(
    top_k=3,
    relevance_score=0.3,
)
```

意義：

| 設定 | 用途 |
|---|---|
| `top_k=3` | 最多取回 3 筆 Memory |
| `relevance_score=0.3` | 只取回相關度高於 0.3 的內容 |

---

# 7. Step 5：修改 `main.py`

開啟：

```text
app/CustomerSupport/main.py
```

主要要做三件事：

1. 匯入 Memory Session Manager
2. 從 Runtime Context 取得 `session_id` 與 `user_id`
3. 建立帶有 `session_manager` 的 Agent

---

## 7.1 新增 Import

```python
from memory.session import get_memory_session_manager
```

---

## 7.2 建立 System Prompt 常數

```python
SYSTEM_PROMPT = """
You are a helpful and professional customer support assistant
for an e-commerce company.

Your role is to:

- Provide accurate information using the tools available to you.
- Be friendly, patient, and understanding with customers.
- Always offer additional help after answering questions.
- If you cannot help with something, direct customers
  to the appropriate contact.

You have access to tools for looking up return policies,
searching product information, and more.

Additional tools may be available at runtime.
Always check your full tool list and use the most appropriate
tool for each customer request.

Always use tools to get accurate, up-to-date information
rather than guessing.
"""
```

---

## 7.3 修改 Agent 建立函式

工作坊版本：

```python
_agent = None


def get_or_create_agent(session_id, user_id):
    global _agent

    if _agent is None:
        _agent = Agent(
            model=load_model(),
            session_manager=get_memory_session_manager(
                session_id,
                user_id,
            ),
            system_prompt=SYSTEM_PROMPT,
            tools=tools,
        )

    return _agent
```

這裡將 Memory Session Manager 傳入：

```python
session_manager=get_memory_session_manager(
    session_id,
    user_id,
)
```

讓 Strands Agent 可以自動：

- 讀取 Memory
- 寫入 Memory
- 在回答前注入相關 Memory
- 在對話結束後進行抽取與摘要

---

## 7.4 修改 `invoke`

```python
@app.entrypoint
async def invoke(payload, context):
    log.info("Invoking Agent...")

    session_id = context.session_id
    user_id = context.request_headers[
        "x-amzn-bedrock-agentcore-runtime-custom-user-id"
    ]

    if not session_id or not user_id:
        raise ValueError(
            "session_id and user_id are required. "
            "Pass --session-id and --user-id when invoking."
        )

    agent = get_or_create_agent(
        session_id,
        user_id,
    )

    stream = agent.stream_async(
        payload.get("prompt")
    )

    async for event in stream:
        if (
            "data" in event
            and isinstance(event["data"], str)
        ):
            yield event["data"]
```

---

## 7.5 `session_id` 與 `user_id` 的差異

### `session_id`

代表一次對話 Session。

```text
同一次連續對話
＝相同 session_id
```

換一個 `session_id`，代表開啟新的對話。

---

### `user_id`

代表使用者本人。

```text
Sarah 的不同 Session
＝不同 session_id
＋相同 user_id
```

AgentCore Memory 能跨 Session 記住使用者，靠的是相同 `user_id`。

---

# 8. 重要提醒：工作坊範例的 Global Agent 問題

工作坊文字說明是「每個 Session / User 建立一個 Agent」，但原始程式使用：

```python
_agent = None
```

這其實只會建立一個全域 Agent。

第一次呼叫後，之後即使傳入其他 `session_id` 或 `user_id`，仍可能重用第一次建立的 Session Manager。

更嚴謹的寫法是依照 `(session_id, user_id)` 分別快取：

```python
_agents = {}


def get_or_create_agent(session_id: str, user_id: str):
    key = (session_id, user_id)

    if key not in _agents:
        _agents[key] = Agent(
            model=load_model(),
            session_manager=get_memory_session_manager(
                session_id,
                user_id,
            ),
            system_prompt=SYSTEM_PROMPT,
            tools=tools,
        )

    return _agents[key]
```

這樣才能真正做到：

```text
不同 User
＋
不同 Session
＝
不同 Agent Session Manager
```

> 若只是照工作坊做單一使用者測試，原始版本可能仍可運作；正式系統則不建議用單一全域 `_agent`。

---

# 9. Step 6：允許 Custom User Header

目前 `user_id` 從這個 Header 取得：

```text
X-Amzn-Bedrock-AgentCore-Runtime-Custom-User-Id
```

因此必須在 `agentcore.json` 中加入 Allowlist。

開啟：

```text
agentcore/agentcore.json
```

在 Runtime 設定加入：

```json
"requestHeaderAllowlist": [
  "X-Amzn-Bedrock-AgentCore-Runtime-Custom-User-Id"
]
```

Runtime 設定應類似：

```json
{
  "runtimes": [
    {
      "name": "CustomerSupport",
      "build": "CodeZip",
      "entrypoint": "main.py",
      "codeLocation": "app/CustomerSupport/",
      "runtimeVersion": "PYTHON_3_14",
      "networkMode": "PUBLIC",
      "protocol": "HTTP",
      "requestHeaderAllowlist": [
        "X-Amzn-Bedrock-AgentCore-Runtime-Custom-User-Id"
      ]
    }
  ]
}
```

---

## 為什麼要加入 Allowlist？

AgentCore Runtime 不會預設把所有自訂 Header 傳進 Agent。

只有加入：

```text
requestHeaderAllowlist
```

的 Header，才會出現在：

```python
context.request_headers
```

否則這段可能讀不到：

```python
context.request_headers[
    "x-amzn-bedrock-agentcore-runtime-custom-user-id"
]
```

---

## 正式系統的安全提醒

本 Lab 直接從自訂 Header 接收 `user_id`，方便測試。

但正式環境不應完全信任使用者自行填入的 Header，否則任何人都可能冒充其他使用者。

正式設計應從：

```text
Authorization Token
→ 驗證後的 Claims
→ 取得 User ID / Actor ID
```

工作坊會在後續 Security Lab 處理這件事。

---

# 10. Step 7：部署 Memory

AgentCore Memory 是 AWS 雲端服務，不能只靠本機程式啟用。

執行：

```powershell
agentcore deploy -y -v
```

參數：

| 參數 | 用途 |
|---|---|
| `-y` | 自動確認部署 |
| `-v` | 顯示詳細部署資訊 |

部署時應看到類似：

```text
✓ Load deployment target
✓ Validate project
✓ Build CDK project
✓ Synthesize CloudFormation
✓ Deploy to AWS
  - AWS::IAM::Role
  - AWS::BedrockAgentCore::Memory
  - AWS::BedrockAgentCore::Runtime
✓ Persist deployment state
```

AgentCore CLI 會：

1. 讀取 `agentcore.json`
2. 建置 CDK Project
3. 產生 CloudFormation
4. 建立 `SharedMemory`
5. 更新既有 Runtime
6. 重新部署 Agent 程式
7. 保存部署狀態

---

# 11. Step 8：第一次對話，教 Agent 認識 Sarah

建立第一個 Session：

```powershell
$SESSION_A = [guid]::NewGuid().ToString()
```

呼叫 Agent：

```powershell
agentcore invoke `
  "My name is Sarah and I prefer email updates. I recently bought a Smart Watch." `
  --session-id $SESSION_A `
  -H "X-Amzn-Bedrock-AgentCore-Runtime-Custom-User-Id: Sarah" `
  --stream
```

這次呼叫的識別方式：

```text
Session ID：隨機 UUID
User ID：Sarah
```

AgentCore Memory 會在對話後，非同步處理：

```text
Sarah 的姓名
Sarah 偏好 Email 通知
Sarah 最近買了 Smart Watch
```

---

# 12. Step 9：等待 Memory 完成抽取

Memory Extraction 是非同步執行，不會立刻完成。

等待約 1～2 分鐘：

```powershell
Start-Sleep -Seconds 120
```

如果太快測試，第二個 Session 可能暫時讀不到 Memory。

---

# 13. Step 10：建立新 Session 測試跨 Session 記憶

建立另一個 Session：

```powershell
$SESSION_B = [guid]::NewGuid().ToString()
```

再次呼叫 Agent：

```powershell
agentcore invoke `
  "Do you know anything about me?" `
  --session-id $SESSION_B `
  -H "X-Amzn-Bedrock-AgentCore-Runtime-Custom-User-Id: Sarah" `
  --stream
```

注意：

```text
SESSION_A ≠ SESSION_B
```

但：

```text
User ID 都是 Sarah
```

預期 Agent 能回答：

```text
Yes, I know a few things about you:

1. Your name is Sarah.
2. You prefer email updates.
3. You recently purchased a Smart Watch.
```

這代表：

```text
不同 Session
＋
相同 User ID
＝
成功讀取跨 Session Memory
```

---

# 14. Memory 背後的實際流程

## 第一次對話後

```text
使用者輸入
    ↓
Agent 回答
    ↓
Memory Service 非同步分析對話
    ↓
SEMANTIC 抽取事實
    ↓
SUMMARIZATION 產生摘要
    ↓
寫入 AgentCore Memory
```

---

## 第二次對話前

```text
新 Session 問題
    ↓
根據 User ID 搜尋相關 Memory
    ↓
取回 Sarah 的事實
    ↓
注入 Agent Context
    ↓
Agent 產生個人化回答
```

---

# 15. 兩種策略實際保存的內容

| 對話內容 | Strategy | 保存結果 |
|---|---|---|
| `My name is Sarah` | `SEMANTIC` | 使用者姓名是 Sarah |
| `I prefer email updates` | `SEMANTIC` | Sarah 偏好 Email 更新 |
| 完整對話 | `SUMMARIZATION` | 壓縮後的 Session 摘要 |

---

# 16. 常見錯誤排查

## 16.1 `MEMORY_ID` 是 `None`

可能原因：

- 尚未部署
- Memory Resource 沒有建立成功
- Runtime 沒有注入環境變數
- 環境變數名稱不正確

檢查：

```text
MEMORY_SHAREDMEMORY_ID
```

Memory 名稱如果不是 `SharedMemory`，環境變數名稱也可能不同。

---

## 16.2 找不到 Custom Header

錯誤可能出現在：

```python
context.request_headers[
    "x-amzn-bedrock-agentcore-runtime-custom-user-id"
]
```

檢查：

- `agentcore.json` 是否加入 Header Allowlist
- Header 名稱拼字是否正確
- 是否重新部署 Runtime
- CLI 是否有傳入 `-H`

---

## 16.3 第二個 Session 沒有記住資料

檢查：

1. 是否等待 1～2 分鐘
2. 第二次是否仍使用相同 User ID
3. `session_id` 是否真的不同
4. Memory Resource 是否部署成功
5. Semantic Strategy 是否啟用
6. Runtime 是否有 Memory ID
7. `session_manager` 是否正確傳入 Agent

---

## 16.4 不同使用者卻讀到同一份 Memory

可能原因：

- 使用全域 `_agent`
- Session Manager 被重用
- User ID 傳錯
- Namespace 設計錯誤

建議改成：

```python
_agents[(session_id, user_id)]
```

而不是單一：

```python
_agent
```

---

## 16.5 本機 `agentcore dev` 無法完整測試 Memory

原因：

```text
AgentCore Memory 是雲端服務
```

本機可以測試 Python 程式是否能啟動，但完整的 Memory Resource、環境變數注入與跨 Session 儲存，需要先部署到 AgentCore Runtime。

---

# 17. 完整操作順序

```text
Step 1
停止 Lab 1 的 Dev Server
    ↓
Step 2
agentcore add memory
    ↓
Step 3
確認 agentcore.json
    ↓
Step 4
建立 memory/session.py
    ↓
Step 5
在 main.py 匯入 Session Manager
    ↓
Step 6
從 Runtime Context 取得 Session ID 與 User ID
    ↓
Step 7
把 Session Manager 傳入 Agent
    ↓
Step 8
在 agentcore.json Allowlist Custom Header
    ↓
Step 9
agentcore deploy -y -v
    ↓
Step 10
用 SESSION_A 告訴 Agent 使用者資訊
    ↓
Step 11
等待 1～2 分鐘
    ↓
Step 12
用 SESSION_B、相同 User ID 再次詢問
    ↓
Step 13
確認 Agent 能跨 Session 讀取 Memory
```

---

# 18. 指令速查表

| 指令 | 用途 |
|---|---|
| `agentcore add memory` | 在本機設定中加入 Memory Resource |
| `Get-Content agentcore\agentcore.json` | 查看 AgentCore 設定 |
| `mkdir ...\memory` | 建立 Memory 模組目錄 |
| `agentcore deploy -y -v` | 建立 Memory 並更新 Runtime |
| `[guid]::NewGuid()` | 產生新的 Session UUID |
| `agentcore invoke` | 呼叫已部署的 Agent |
| `--session-id` | 指定本次對話 Session |
| `-H` | 傳入 Custom User ID Header |
| `Start-Sleep -Seconds 120` | 等待 Memory 非同步抽取 |

---

# 19. 最後檢查清單

- [ ] Lab 1 已完成
- [ ] Dev Server 已停止
- [ ] `SharedMemory` 已加入 `agentcore.json`
- [ ] 已啟用 `SEMANTIC`
- [ ] 已啟用 `SUMMARIZATION`
- [ ] 已建立 `memory/__init__.py`
- [ ] 已建立 `memory/session.py`
- [ ] `main.py` 已匯入 Memory Session Manager
- [ ] Agent 已傳入 `session_manager`
- [ ] Runtime Header Allowlist 已設定
- [ ] 已重新部署 Agent
- [ ] 第一次呼叫已傳入 User ID
- [ ] 已等待 1～2 分鐘
- [ ] 第二次使用不同 Session ID
- [ ] 第二次仍使用相同 User ID
- [ ] Agent 能成功回想使用者資訊

---

# 20. 一句話總結

本 Lab 的核心是：

```text
建立 AgentCore Memory Resource
→ 用 Session Manager 接到 Strands Agent
→ 用 User ID 區分使用者
→ 用 Session ID 區分對話
→ 部署到 AWS
→ 讓 Agent 跨 Session 記住使用者
```
