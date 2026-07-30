# Amazon Bedrock AgentCore：一步一步建立 Customer Support Agent

## 0. 教學目標

本教學將帶你從零開始建立一個可在本機執行、可部署到 AWS 的 Customer Support Agent。

完成後，Agent 將具備以下能力：

- 查詢不同商品類別的退貨政策
- 查詢商品名稱、價格、分類與保固資訊
- 透過 MCP 連接 Exa AI 進行網路搜尋
- 同時使用多個工具完成複合問題
- 在本機透過 Agent Inspector 測試
- 部署到 Amazon Bedrock AgentCore Runtime

---

# 1. 建立前準備

開始前請先確認：

- 已開啟 Kiro IDE
- 已開啟 Kiro 內建 Terminal
- 已安裝並可使用 AgentCore CLI
- 已取得 AWS Credential
- AWS Region 設定為工作坊指定區域，例如：

```text
us-west-2
```

如果是在 AWS Event 環境中，AWS Credential 通常是臨時憑證，可能包含：

```powershell
$Env:AWS_ACCESS_KEY_ID="..."
$Env:AWS_SECRET_ACCESS_KEY="..."
$Env:AWS_SESSION_TOKEN="..."
$Env:AWS_DEFAULT_REGION="us-west-2"
```

> 注意：AWS Credential 屬於敏感資料，不要提交到 GitHub，也不要貼到公開聊天室。

---

# 2. 建立 AgentCore 專案

## 2.1 在 Kiro 開啟 Terminal

快捷鍵：

### Windows / Linux

```text
Ctrl + `
```

### macOS

```text
Cmd + `
```

---

## 2.2 執行專案建立指令

### Windows PowerShell

```powershell
agentcore create `
  --name CustomerSupport `
  --framework Strands `
  --model-provider Bedrock `
  --memory none
```

### macOS / Linux

```bash
agentcore create \
  --name CustomerSupport \
  --framework Strands \
  --model-provider Bedrock \
  --memory none
```

參數說明：

| 參數 | 用途 |
|---|---|
| `--name CustomerSupport` | 建立名稱為 CustomerSupport 的 Agent |
| `--framework Strands` | 使用 Strands Agents SDK |
| `--model-provider Bedrock` | 使用 Amazon Bedrock 作為模型供應者 |
| `--memory none` | 此階段先不啟用持久化記憶 |

也可以使用預設設定快速建立：

```powershell
agentcore create --defaults
```

---

## 2.3 確認建立結果

成功後，Terminal 會看到類似內容：

```text
[done] Create CustomerSupport/ project directory
[done] Prepare agentcore/ directory
[done] Initialize git repository
[done] Add agent to project
[done] Set up Python environment
```

建立完成後，專案中會有兩個主要區域：

```text
CustomerSupport/
├── app/
└── agentcore/
```

其中：

```text
app/
```

放 Agent 程式。

```text
agentcore/
```

放 AgentCore 設定與 AWS 部署相關內容。

---

# 3. 開啟專案

如果 Kiro 沒有自動開啟新專案：

1. 回到 Kiro 首頁。
2. 點選 `Open a project`。
3. 找到 `CustomerSupport` 資料夾。
4. 點選開啟。

開啟後，在 Terminal 進入專案：

```powershell
cd CustomerSupport
```

---

# 4. 認識專案結構

建立後的專案大致如下：

```text
CustomerSupport/
├── AGENTS.md
├── README.md
├── agentcore/
│   ├── agentcore.json
│   ├── aws-targets.json
│   ├── .env.local
│   ├── .cli/
│   │   └── deployed-state.json
│   ├── .llm-context/
│   └── cdk/
└── app/
    └── CustomerSupport/
        ├── main.py
        ├── model/
        │   └── load.py
        ├── mcp_client/
        │   └── client.py
        └── pyproject.toml
```

---

## 4.1 `main.py`

位置：

```text
app/CustomerSupport/main.py
```

這是 Agent 的主要程式入口。

它負責：

- 建立 AgentCore App
- 建立 Strands Agent
- 設定 System Prompt
- 註冊 Tools
- 加入 MCP Client
- 接收使用者 Prompt
- 串流回傳 Agent 回應

---

## 4.2 `model/load.py`

位置：

```text
app/CustomerSupport/model/load.py
```

負責載入 Amazon Bedrock 模型。

預設可能使用 Claude Sonnet 4.5，但實際模型需以工作坊設定與 AWS 帳號可使用的模型為準。

---

## 4.3 `mcp_client/client.py`

位置：

```text
app/CustomerSupport/mcp_client/client.py
```

負責建立 MCP Client。

本工作坊使用 Exa AI MCP，提供 Agent 網路搜尋能力。

---

## 4.4 `pyproject.toml`

位置：

```text
app/CustomerSupport/pyproject.toml
```

負責定義 Python 套件依賴。

AgentCore CLI 會透過 `uv` 根據此檔案安裝套件。

---

## 4.5 `agentcore.json`

位置：

```text
agentcore/agentcore.json
```

這是 AgentCore 主要設定檔，可能包含：

- Agent
- Runtime
- Memory
- Gateway
- Credential
- 部署資源

---

## 4.6 `.cli/`

位置：

```text
agentcore/.cli/
```

由 AgentCore CLI 自動管理。

其中：

```text
deployed-state.json
```

會記錄部署完成的資源，例如：

- Runtime ID
- Runtime ARN
- Memory ID
- Gateway URL

不建議手動修改。

---

## 4.7 `.llm-context/`

位置：

```text
agentcore/.llm-context/
```

這裡放的是自動產生的 TypeScript 型別定義，讓 Kiro 或其他 AI Coding Assistant 理解 AgentCore 設定格式。

不建議手動修改。

---

## 4.8 `cdk/`

位置：

```text
agentcore/cdk/
```

這是一個 AWS CDK 專案，用來產生 CloudFormation 並部署：

- AgentCore Runtime
- IAM Role
- Memory
- Gateway
- 其他 AWS 資源

初學階段通常不需要修改。

---

# 5. 修改 Agent 程式

## 5.1 開啟 `main.py`

在 Kiro 左側檔案總管依序展開：

```text
app
└── CustomerSupport
    └── main.py
```

將 `main.py` 原本內容全部刪除，再換成以下程式。

---

## 5.2 完整 `main.py`

```python
from strands import Agent, tool
from bedrock_agentcore.runtime import BedrockAgentCoreApp
from model.load import load_model
from mcp_client.client import get_streamable_http_mcp_client


app = BedrockAgentCoreApp()
log = app.logger


# Exa AI MCP client，用於網路搜尋
mcp_clients = [get_streamable_http_mcp_client()]


# ============================================================
# Customer Support 測試資料
# ============================================================

RETURN_POLICIES = {
    "electronics": {
        "window": "30 days",
        "condition": (
            "Original packaging required, "
            "must be unused or defective"
        ),
        "refund": "Full refund to original payment method",
    },
    "accessories": {
        "window": "14 days",
        "condition": "Must be in original packaging, unused",
        "refund": "Store credit or exchange",
    },
    "audio": {
        "window": "30 days",
        "condition": "Defective items only after 15 days",
        "refund": "Full refund within 15 days, replacement after",
    },
}


PRODUCTS = {
    "PROD-001": {
        "name": "Wireless Headphones",
        "price": 79.99,
        "category": "audio",
        "description": (
            "Noise-cancelling Bluetooth headphones "
            "with 30h battery life"
        ),
        "warranty_months": 12,
    },
    "PROD-002": {
        "name": "Smart Watch",
        "price": 249.99,
        "category": "electronics",
        "description": (
            "Fitness tracker with heart rate monitor, "
            "GPS, and 5-day battery"
        ),
        "warranty_months": 24,
    },
    "PROD-003": {
        "name": "Laptop Stand",
        "price": 39.99,
        "category": "accessories",
        "description": (
            "Adjustable aluminum laptop stand "
            "for ergonomic desk setup"
        ),
        "warranty_months": 6,
    },
    "PROD-004": {
        "name": "USB-C Hub",
        "price": 54.99,
        "category": "accessories",
        "description": (
            "7-in-1 USB-C hub with HDMI, USB-A, "
            "SD card reader, and ethernet"
        ),
        "warranty_months": 12,
    },
    "PROD-005": {
        "name": "Mechanical Keyboard",
        "price": 129.99,
        "category": "electronics",
        "description": (
            "RGB mechanical keyboard with Cherry MX switches"
        ),
        "warranty_months": 24,
    },
}


# ============================================================
# Tool 1：查詢退貨政策
# ============================================================

@tool
def get_return_policy(product_category: str) -> str:
    """Get return policy information for a product category.

    Args:
        product_category:
            Product category, such as electronics,
            accessories, or audio.

    Returns:
        Formatted return policy details.
    """

    category = product_category.lower()

    if category in RETURN_POLICIES:
        policy = RETURN_POLICIES[category]

        return (
            f"Return policy for {category}: "
            f"Window: {policy['window']}, "
            f"Condition: {policy['condition']}, "
            f"Refund: {policy['refund']}"
        )

    return (
        f"No specific return policy found for "
        f"'{product_category}'. "
        "Please contact support for details."
    )


# ============================================================
# Tool 2：查詢商品資訊
# ============================================================

@tool
def get_product_info(query: str) -> str:
    """Search for product information by name, ID, or keyword.

    Args:
        query:
            Product name, product ID, or search keyword.

    Returns:
        Product name, price, category,
        description, and warranty.
    """

    query_lower = query.lower()

    # 先嘗試用 Product ID 查詢
    if query.upper() in PRODUCTS:
        product_id = query.upper()
        product = PRODUCTS[product_id]

        return (
            f"{product['name']} ({product_id}): "
            f"${product['price']}, "
            f"Category: {product['category']}, "
            f"{product['description']}, "
            f"Warranty: {product['warranty_months']} months"
        )

    # 再使用關鍵字查詢
    results = []

    for product_id, product in PRODUCTS.items():
        is_match = (
            query_lower in product["name"].lower()
            or query_lower in product["description"].lower()
            or query_lower in product["category"].lower()
        )

        if is_match:
            results.append(
                f"{product_id}: "
                f"{product['name']} - "
                f"${product['price']} - "
                f"{product['description']}"
            )

    if results:
        return "Found products:\n" + "\n".join(results)

    return f"No products found matching '{query}'."


# ============================================================
# 建立 Tool 清單
# ============================================================

tools = [
    get_return_policy,
    get_product_info,
]


# 將 MCP Client 加入 Tool 清單
for mcp_client in mcp_clients:
    if mcp_client:
        tools.append(mcp_client)


# ============================================================
# 建立 Agent
# ============================================================

_agent = None


def get_or_create_agent():
    """建立 Agent，並重複使用同一個 Agent 實例."""

    global _agent

    if _agent is None:
        _agent = Agent(
            model=load_model(),
            system_prompt="""
You are a helpful and professional customer support assistant
for an e-commerce company.

Your role is to:

- Provide accurate information using the tools available to you.
- Be friendly, patient, and understanding with customers.
- Always offer additional help after answering questions.
- If you cannot help with something, direct customers
  to the appropriate contact.

You have access to tools for:

- Looking up return policies.
- Searching product information.
- Searching additional information through MCP tools.

Additional tools may be available at runtime.
Always inspect the available tool list and select
the most appropriate tool for the customer's request.

Always use tools to obtain accurate and current information
rather than guessing.
""",
            tools=tools,
        )

    return _agent


# ============================================================
# AgentCore 進入點
# ============================================================

@app.entrypoint
async def invoke(payload, context):
    """接收使用者 Prompt，並串流回傳 Agent 回應."""

    log.info("Invoking Agent...")

    agent = get_or_create_agent()
    prompt = payload.get("prompt")

    stream = agent.stream_async(prompt)

    async for event in stream:
        if "data" in event and isinstance(event["data"], str):
            yield event["data"]


# ============================================================
# 本機直接執行入口
# ============================================================

if __name__ == "__main__":
    app.run()
```

---

# 6. 理解程式的組成

## 6.1 建立 AgentCore App

```python
app = BedrockAgentCoreApp()
log = app.logger
```

作用：

- 建立 AgentCore Runtime 應用程式
- 提供 Agent 執行入口
- 提供日誌功能

---

## 6.2 建立 MCP Client

```python
mcp_clients = [get_streamable_http_mcp_client()]
```

作用：

- 連接 Exa AI MCP Server
- 讓 Agent 可以使用網路搜尋工具

---

## 6.3 建立 Tool

```python
@tool
def get_return_policy(...):
    ...
```

`@tool` 會把一般 Python Function 註冊成 Agent 可以選擇與呼叫的工具。

Tool 的三個重要部分是：

1. Function Name
2. Docstring
3. Parameter

Agent 會根據這些資訊判斷什麼時候要使用該 Tool。

---

## 6.4 建立 Tools 清單

```python
tools = [
    get_return_policy,
    get_product_info,
]
```

Agent 只會看到放進 `tools` 清單的工具。

之後再加入 MCP Client：

```python
for mcp_client in mcp_clients:
    if mcp_client:
        tools.append(mcp_client)
```

---

## 6.5 建立 Agent

```python
_agent = Agent(
    model=load_model(),
    system_prompt="...",
    tools=tools,
)
```

三個主要設定：

| 設定 | 用途 |
|---|---|
| `model` | 指定使用哪個 LLM |
| `system_prompt` | 規定 Agent 的角色與行為 |
| `tools` | 指定 Agent 可以使用的工具 |

---

## 6.6 建立 AgentCore 進入點

```python
@app.entrypoint
async def invoke(payload, context):
```

AgentCore Runtime 會透過這個函式把使用者請求送進 Agent。

使用者問題從：

```python
payload.get("prompt")
```

取得。

---

## 6.7 串流回應

```python
stream = agent.stream_async(prompt)
```

Agent 會以串流方式產生回應。

接著：

```python
async for event in stream:
```

逐段取得模型輸出。

---

# 7. 啟動本機 Agent

完成 `main.py` 後，在專案根目錄執行：

```powershell
agentcore dev
```

AgentCore CLI 會自動：

1. 檢查 `.venv`
2. 建立 Python 虛擬環境
3. 執行 `uv sync`
4. 安裝 `pyproject.toml` 中的套件
5. 使用 Uvicorn 啟動 Agent
6. 使用 Port 8080
7. 啟用 Hot Reload
8. 開啟 Agent Inspector

---

# 8. 使用 Agent Inspector 測試

在 Agent Inspector 中，依序測試以下問題。

---

## 8.1 測試退貨政策 Tool

輸入：

```text
What's the return policy for electronics?
```

預期流程：

```text
使用者問題
    ↓
Agent 判斷需要退貨政策
    ↓
呼叫 get_return_policy("electronics")
    ↓
Tool 回傳 electronics 退貨政策
    ↓
Agent 整理回應
```

預期內容：

- 退貨期限為 30 days
- 需要原包裝
- 商品需未使用或有瑕疵
- 退款至原付款方式

---

## 8.2 測試商品查詢 Tool

輸入：

```text
Tell me about the Wireless Headphones
```

預期呼叫：

```python
get_product_info("headphones")
```

預期內容：

- 商品名稱
- 商品價格
- 商品描述
- 保固月份

---

## 8.3 測試 MCP 網路搜尋

輸入：

```text
Search for common Bluetooth headphone troubleshooting tips
```

預期流程：

```text
Agent 判斷本機 Tool 無法取得足夠資訊
    ↓
選擇 Exa AI MCP 搜尋工具
    ↓
搜尋網路資訊
    ↓
整理成回應
```

此測試需要 MCP Client 與 Exa AI 設定正常。

---

## 8.4 測試多工具問題

輸入：

```text
I bought a Smart Watch (PROD-002)
and want to return it.
What's the return policy?
```

預期流程：

```text
1. 呼叫 get_product_info("PROD-002")
2. 找到商品分類為 electronics
3. 呼叫 get_return_policy("electronics")
4. 整合商品資訊與退貨政策
5. 產生完整回答
```

這個測試可以確認 Agent 是否具備多步驟 Tool Calling 能力。

---

# 9. 查看 Agent Trace

Agent Inspector 中可以查看：

- Agent 選擇了哪個 Tool
- Tool 的輸入參數
- Tool 的輸出結果
- 輸入 Token
- 輸出 Token
- 每個步驟花費時間
- Agent 最後產生的回答

判斷 Agent 是否正常時，不要只看最後答案，也要查看 Trace。

例如：

```text
最後回答看起來正確
```

不一定代表流程正確。

Agent 可能只是依靠模型知識回答，而沒有呼叫 Tool。

因此應確認：

```text
Tool Used
Tool Input
Tool Output
```

是否符合預期。

---

# 10. 使用 CLI 測試 Agent

除了 Agent Inspector，也可以直接在 Terminal 測試。

---

## 10.1 第一個 Terminal：啟動伺服器

```powershell
agentcore dev --no-browser --logs
```

作用：

- 不開啟瀏覽器
- 顯示伺服器日誌
- 持續監聽程式變更

---

## 10.2 第二個 Terminal：呼叫本機 Agent

```powershell
agentcore dev "What can you do?" --stream
```

此指令會：

1. 將 Prompt 傳給本機 Agent
2. 以串流方式輸出回答

這種方式適合：

- CLI 測試
- 自動化腳本
- CI/CD
- 快速確認 Agent 是否可用

---

## 10.3 Split Terminal 注意事項

如果你是在 AWS Event 使用臨時 Credential：

新開 Terminal 或 Split Terminal 後，AWS 環境變數可能沒有自動帶入。

需要重新設定：

```powershell
$Env:AWS_ACCESS_KEY_ID="..."
$Env:AWS_SECRET_ACCESS_KEY="..."
$Env:AWS_SESSION_TOKEN="..."
$Env:AWS_DEFAULT_REGION="us-west-2"
```

---

# 11. 部署 Agent 到 AWS

本機測試完成後，執行：

```powershell
agentcore deploy
```

AgentCore CLI 會自動：

1. 封裝 Agent 程式
2. 整理 Python 依賴
3. 讀取 AgentCore 設定
4. 執行 AWS CDK
5. 產生 CloudFormation Template
6. 建立 IAM Role
7. 建立 Runtime
8. 部署到 AgentCore Runtime
9. 記錄部署狀態

---

# 12. 查看部署狀態

執行：

```powershell
agentcore status
```

可以確認：

- Agent 是否成功部署
- Runtime 狀態
- 部署目標
- AWS 資源資訊

---

# 13. 呼叫已部署的 Agent

執行：

```powershell
agentcore invoke "What can you do?"
```

此時的請求會送到 AWS 上的 AgentCore Runtime，而不是本機伺服器。

---

# 14. 完整建立流程

```text
Step 1
取得 AWS Credential
    ↓
Step 2
執行 agentcore create
    ↓
Step 3
開啟 CustomerSupport 專案
    ↓
Step 4
認識 app/ 與 agentcore/
    ↓
Step 5
修改 app/CustomerSupport/main.py
    ↓
Step 6
建立 get_return_policy Tool
    ↓
Step 7
建立 get_product_info Tool
    ↓
Step 8
加入 Exa AI MCP Client
    ↓
Step 9
建立 Strands Agent
    ↓
Step 10
執行 agentcore dev
    ↓
Step 11
使用 Inspector 測試 Tool Calling
    ↓
Step 12
使用 CLI 測試
    ↓
Step 13
執行 agentcore deploy
    ↓
Step 14
執行 agentcore status
    ↓
Step 15
使用 agentcore invoke 呼叫雲端 Agent
```

---

# 15. 每個指令的用途

| 指令 | 用途 |
|---|---|
| `agentcore create` | 建立 AgentCore 專案骨架 |
| `cd CustomerSupport` | 進入專案資料夾 |
| `agentcore dev` | 啟動本機 Agent 與 Inspector |
| `agentcore dev --no-browser --logs` | 不開瀏覽器並顯示日誌 |
| `agentcore dev "..." --stream` | 從 CLI 呼叫本機 Agent |
| `agentcore deploy` | 部署 Agent 至 AWS |
| `agentcore status` | 查看部署狀態 |
| `agentcore invoke "..."` | 呼叫已部署的 Agent |

---

# 16. 常見問題

## 16.1 `agentcore create` 為什麼產生很多檔案？

因為它不是建立空白 Python 專案，而是一次產生：

- Agent 程式
- Strands Agent 範例
- Bedrock 模型設定
- MCP Client
- Python 虛擬環境
- Python 依賴
- AgentCore 設定
- CDK 部署專案
- Git Repository
- AI Coding Assistant Context

---

## 16.2 哪些檔案主要需要修改？

初學階段優先看：

```text
app/CustomerSupport/main.py
app/CustomerSupport/model/load.py
app/CustomerSupport/pyproject.toml
agentcore/agentcore.json
```

---

## 16.3 哪些資料夾不建議修改？

```text
agentcore/.cli/
agentcore/.llm-context/
```

這些由 CLI 自動管理。

---

## 16.4 本機可以執行，但部署失敗怎麼辦？

優先檢查：

1. AWS Credential 是否過期
2. AWS Region 是否正確
3. IAM 權限是否足夠
4. Bedrock 模型是否已開放
5. `agentcore status`
6. `.cli/logs/`
7. CloudFormation Event
8. CloudWatch Logs

---

## 16.5 Agent 回答正確，但沒有呼叫 Tool？

檢查：

- Tool Name 是否清楚
- Docstring 是否描述適用情境
- Tool Parameter 是否清楚
- System Prompt 是否要求使用 Tool
- Tools 是否有放進 `tools` 清單
- Inspector Trace 是否顯示 Tool Call

---

# 17. 本 Lab 完成後的成果

完成本教學後，你會得到一個 Customer Support Agent，具備：

```text
商品查詢
退貨政策查詢
MCP 網路搜尋
多工具協作
本機 Agent Inspector
CLI 測試
AWS AgentCore Runtime 部署
```

---

# 18. 後續可繼續擴充

完成 Agent Prototype 後，可以繼續加入：

1. Persistent Memory
2. AgentCore Gateway
3. Credentials 與權限控制
4. Production Observability
5. Session Management
6. Agent Evaluation
7. Customer Chat Interface
8. Policy 與 Action Governance
9. Agent Quality Optimization

---

# 19. 最後檢查清單

部署前確認：

- [ ] AWS Credential 已設定
- [ ] Region 正確
- [ ] `CustomerSupport` 專案建立成功
- [ ] `main.py` 已更新
- [ ] `get_return_policy` 測試成功
- [ ] `get_product_info` 測試成功
- [ ] MCP 搜尋測試成功
- [ ] 多工具測試成功
- [ ] Inspector Trace 符合預期
- [ ] `agentcore dev` 可正常啟動
- [ ] `agentcore deploy` 執行成功
- [ ] `agentcore status` 顯示正常
- [ ] `agentcore invoke` 可呼叫雲端 Agent

---

# 20. 一句話總結

本教學的核心流程是：

```text
使用 AgentCore CLI 建立專案
→ 修改 main.py 加入 Tools
→ 使用 Strands Agent 組合模型與工具
→ 在本機測試 Tool Calling
→ 部署到 Amazon Bedrock AgentCore Runtime
```
