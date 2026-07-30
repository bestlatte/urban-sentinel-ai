# Amazon Bedrock AgentCore Lab 3：使用 Gateway 集中管理 Tools

## 0. 本 Lab 要完成什麼？

在 Lab 1 與 Lab 2 中，Agent 的工具主要有兩種來源：

```text
本機 Python Tool
＋
直接連線的 Exa AI MCP
```

本 Lab 會新增 **Amazon Bedrock AgentCore Gateway**，把既有的 AWS Lambda 包裝成 MCP Tool，讓 Agent 可以透過統一的 Gateway Endpoint 發現並呼叫它。

完成後的架構：

```text
CustomerSupport Agent
├── 本機 Tool：get_return_policy
├── 本機 Tool：get_product_info
├── Exa AI MCP：網路搜尋
└── AgentCore Gateway
    └── WarrantyCheck Lambda
        └── check_warranty Tool
```

---

# 1. 先理解 AgentCore Gateway

AgentCore Gateway 是一個受管理的 MCP 相容代理層。

它可以把原本不是為 Agent 設計的服務，轉換成 Agent 可以發現與呼叫的 Tool。

支援的 Target 類型包括：

- AWS Lambda
- Amazon API Gateway REST API
- OpenAPI HTTP Service
- Smithy Model
- MCP Server
- 第三方整合模板

本 Lab 使用：

```text
AWS Lambda
→ AgentCore Gateway
→ MCP Tool
```

---

# 2. 為什麼要使用 Gateway？

如果所有 Tool 都直接寫在 `main.py`：

```python
@tool
def check_warranty(...):
    ...
```

會遇到幾個問題：

- Tool 與 Agent 程式高度耦合
- 其他 Agent 不容易共用
- 權限與驗證分散
- Tool 數量增加後難以管理
- 既有 Lambda 或 API 必須重新包裝進 Agent 程式

加入 Gateway 後：

```text
既有 Lambda
    ↓
提供 Tool Schema
    ↓
AgentCore Gateway MCP 化
    ↓
多個 Agent 共用
```

原本的 Lambda 程式不需要修改。

---

# 3. 前置條件

開始前請確認：

- 已完成 Lab 1
- 已完成 Lab 2
- CustomerSupport Agent 已部署
- AgentCore Memory 已可運作
- AWS Credential 仍然有效
- AWS Region 正確
- 工作坊提供的 Warranty Lambda 已存在
- Terminal 位於 `CustomerSupport` 專案根目錄

如果 Lab 2 的 Dev Server 還在執行，先停止：

```text
Esc
```

或：

```text
Ctrl + C
```

---

# 4. Step 1：確認 Warranty Lambda

本 Lab 使用一個既有 Lambda：

```text
workshop-warranty-check
```

它模擬另一個團隊維護的保固查詢服務。

Lambda 程式概念如下：

```python
import json


WARRANTIES = {
    "PROD-001": {
        "product": "Wireless Headphones",
        "warranty_months": 12,
        "status": "active",
        "expires": "2027-03-01",
    },
    "PROD-002": {
        "product": "Smart Watch",
        "warranty_months": 24,
        "status": "active",
        "expires": "2028-01-15",
    },
    "PROD-003": {
        "product": "Laptop Stand",
        "warranty_months": 6,
        "status": "expired",
        "expires": "2026-01-01",
    },
    "PROD-004": {
        "product": "USB-C Hub",
        "warranty_months": 12,
        "status": "active",
        "expires": "2027-06-20",
    },
}


def handler(event, context):
    product_id = event.get("product_id", "").upper()

    if product_id in WARRANTIES:
        return {
            "statusCode": 200,
            "body": json.dumps(WARRANTIES[product_id]),
        }

    return {
        "statusCode": 404,
        "body": json.dumps(
            {
                "error": (
                    f"No warranty found for {product_id}"
                )
            }
        ),
    }
```

---

## 4.1 Gateway 呼叫 Lambda 的方式

AgentCore Gateway 會把 Tool 參數直接放進 Lambda Event：

```python
event["product_id"]
```

不是：

```python
event["body"]["product_id"]
```

因此 Lambda 使用：

```python
product_id = event.get("product_id", "")
```

---

# 5. Step 2：取得 Lambda ARN

工作坊已將 Lambda ARN 存入 AWS Systems Manager Parameter Store。

## Windows PowerShell

執行：

```powershell
$WARRANTY_LAMBDA_ARN = aws ssm get-parameter `
  --name "/app/customersupport/agentcore/warranty_check_lambda_arn" `
  --query "Parameter.Value" `
  --output text
```

確認結果：

```powershell
Write-Host "Lambda ARN: $WARRANTY_LAMBDA_ARN"
```

預期輸出類似：

```text
arn:aws:lambda:us-west-2:123456789012:function:workshop-warranty-check
```

---

## macOS / Linux

```bash
WARRANTY_LAMBDA_ARN=$(aws ssm get-parameter \
  --name /app/customersupport/agentcore/warranty_check_lambda_arn \
  --query 'Parameter.Value' \
  --output text)

echo "Lambda ARN: $WARRANTY_LAMBDA_ARN"
```

---

## 5.1 如果取得失敗

可能原因：

- AWS Credential 過期
- Region 錯誤
- Parameter 不存在
- IAM 沒有 `ssm:GetParameter` 權限
- 工作坊資源已被回收

可先確認身分：

```powershell
aws sts get-caller-identity
```

確認 Region：

```powershell
aws configure get region
```

---

# 6. Step 3：建立 Tool Schema

Lambda 本身只有程式與輸入輸出，沒有 Agent 可以理解的工具描述。

因此必須建立 Tool Schema，告訴 Agent：

- Tool 名稱
- Tool 做什麼
- 需要哪些參數
- 哪些參數必填

---

## 6.1 建立資料夾與檔案

### Windows PowerShell

```powershell
New-Item `
  -ItemType Directory `
  -Path app\CustomerSupport\tool `
  -Force
```

```powershell
New-Item `
  app\CustomerSupport\tool\__init__.py `
  -ItemType File `
  -Force
```

```powershell
New-Item `
  app\CustomerSupport\tool\warranty_schema.json `
  -ItemType File `
  -Force
```

建立後：

```text
app/
└── CustomerSupport/
    ├── main.py
    ├── memory/
    ├── mcp_client/
    ├── model/
    └── tool/
        ├── __init__.py
        └── warranty_schema.json
```

---

## 6.2 撰寫 `warranty_schema.json`

開啟：

```text
app/CustomerSupport/tool/warranty_schema.json
```

貼入：

```json
[
  {
    "name": "check_warranty",
    "description": "Check the warranty status of a product by its product ID, for example PROD-001. Returns warranty duration, status, and expiration date.",
    "inputSchema": {
      "type": "object",
      "properties": {
        "product_id": {
          "type": "string",
          "description": "The product ID to check warranty for, for example PROD-001."
        }
      },
      "required": [
        "product_id"
      ]
    }
  }
]
```

---

## 6.3 Schema 欄位用途

| 欄位 | 用途 |
|---|---|
| `name` | Tool 名稱 |
| `description` | Agent 判斷何時使用 Tool |
| `inputSchema` | Tool 參數格式 |
| `properties` | 可傳入的參數 |
| `required` | 必填參數 |

Agent 會閱讀：

```json
"description"
```

來決定是否呼叫 `check_warranty`。

---

## 6.4 重要格式限制

`inputSchema` 必須直接包含：

```json
{
  "type": "object"
}
```

不要寫成：

```json
{
  "inputSchema": {
    "json": {
      "type": "object"
    }
  }
}
```

否則可能出現：

```text
Attribute type null is not yet supported
```

---

# 7. Step 4：建立 Gateway

執行：

```powershell
agentcore add gateway `
  --name my-gateway `
  --runtimes CustomerSupport
```

也可以寫成單行：

```powershell
agentcore add gateway --name my-gateway --runtimes CustomerSupport
```

成功後：

```text
Added gateway 'my-gateway'
```

---

## 7.1 `--runtimes CustomerSupport` 的作用

這個參數會把 Gateway 與 CustomerSupport Runtime 關聯。

部署後，AgentCore Runtime 會自動注入：

```text
AGENTCORE_GATEWAY_MY_GATEWAY_URL
```

Agent 程式可以透過此環境變數取得 Gateway URL。

---

# 8. Step 5：將 Lambda 加入 Gateway Target

## Windows PowerShell

```powershell
agentcore add gateway-target `
  --type lambda-function-arn `
  --name WarrantyCheck `
  --lambda-arn $WARRANTY_LAMBDA_ARN `
  --tool-schema-file app\CustomerSupport\tool\warranty_schema.json `
  --gateway my-gateway
```

成功後：

```text
Added gateway target 'WarrantyCheck'
```

---

## 8.1 參數說明

| 參數 | 用途 |
|---|---|
| `--type lambda-function-arn` | Target 是 Lambda |
| `--name WarrantyCheck` | Target 名稱 |
| `--lambda-arn` | Lambda ARN |
| `--tool-schema-file` | Tool Schema 路徑 |
| `--gateway my-gateway` | 加入指定 Gateway |

---

# 9. Step 6：更新 MCP Client

開啟：

```text
app/CustomerSupport/mcp_client/client.py
```

將內容整理成：

```python
import logging
import os

from mcp.client.streamable_http import (
    streamablehttp_client,
)
from strands.tools.mcp.mcp_client import MCPClient


logger = logging.getLogger(__name__)


EXAMPLE_MCP_ENDPOINT = "https://mcp.exa.ai/mcp"


def get_streamable_http_mcp_client() -> MCPClient:
    """建立 Exa AI MCP Client."""

    return MCPClient(
        lambda: streamablehttp_client(
            EXAMPLE_MCP_ENDPOINT
        )
    )


def get_gateway_mcp_client() -> MCPClient | None:
    """建立 AgentCore Gateway MCP Client."""

    url = os.environ.get(
        "AGENTCORE_GATEWAY_MY_GATEWAY_URL"
    )

    if not url:
        logger.warning(
            "Gateway URL not set. "
            "Gateway tools are unavailable."
        )
        return None

    return MCPClient(
        lambda: streamablehttp_client(url)
    )
```

---

## 9.1 `get_gateway_mcp_client()` 的流程

```text
讀取環境變數
AGENTCORE_GATEWAY_MY_GATEWAY_URL
    ↓
取得 Gateway MCP Endpoint
    ↓
建立 MCP Client
    ↓
Agent 自動發現 Gateway Tools
```

---

## 9.2 為什麼本機可能回傳 `None`？

在本機尚未部署時，通常沒有：

```text
AGENTCORE_GATEWAY_MY_GATEWAY_URL
```

因此：

```python
return None
```

可以避免本機程式因缺少 Gateway URL 而立即失敗。

---

# 10. Step 7：更新 `main.py`

## 10.1 更新 Import

原本：

```python
from mcp_client.client import (
    get_streamable_http_mcp_client,
)
```

改成：

```python
from mcp_client.client import (
    get_gateway_mcp_client,
    get_streamable_http_mcp_client,
)
```

---

## 10.2 更新 MCP Client 清單

```python
mcp_clients = [
    get_streamable_http_mcp_client(),
    get_gateway_mcp_client(),
]
```

此時 Agent 擁有兩個 MCP 來源：

```text
Exa AI MCP
AgentCore Gateway MCP
```

---

## 10.3 保留本機 Tools

本 Lab 不會移除：

```python
get_return_policy
get_product_info
```

因此 Tools 架構為：

```text
本機 Tools
├── get_return_policy
└── get_product_info

MCP Tools
├── Exa AI Search
└── Gateway check_warranty
```

---

## 10.4 移除商品資料中的 Warranty 欄位

因為 Warranty 資料改由 Gateway Lambda 查詢，所以 `PRODUCTS` 不再保存：

```python
"warranty_months"
```

例如：

```python
"PROD-001": {
    "name": "Wireless Headphones",
    "price": 79.99,
    "category": "audio",
    "description": (
        "Noise-cancelling Bluetooth headphones "
        "with 30h battery life"
    ),
}
```

`get_product_info()` 的回傳也不再包含保固月份。

---

# 11. 建議的 `main.py` 核心修改

下面只列出 Lab 3 需要改動的關鍵部分。

```python
from strands import Agent, tool
from bedrock_agentcore.runtime import (
    BedrockAgentCoreApp,
)

from model.load import load_model
from memory.session import (
    get_memory_session_manager,
)
from mcp_client.client import (
    get_gateway_mcp_client,
    get_streamable_http_mcp_client,
)


app = BedrockAgentCoreApp()
log = app.logger


mcp_clients = [
    get_streamable_http_mcp_client(),
    get_gateway_mcp_client(),
]


tools = [
    get_return_policy,
    get_product_info,
]


for mcp_client in mcp_clients:
    if mcp_client:
        tools.append(mcp_client)
```

Agent 建立方式仍然包含 Memory：

```python
agent = Agent(
    model=load_model(),
    session_manager=get_memory_session_manager(
        session_id,
        user_id,
    ),
    system_prompt=SYSTEM_PROMPT,
    tools=tools,
)
```

---

# 12. 重要提醒：Global Agent 問題

工作坊範例仍使用：

```python
_agent = None
```

這代表第一個 Session 建立 Agent 後，後續 Session 可能重用相同 Session Manager。

更嚴謹的寫法：

```python
_agents = {}


def get_or_create_agent(
    session_id: str,
    user_id: str,
):
    key = (
        session_id,
        user_id,
    )

    if key not in _agents:
        _agents[key] = Agent(
            model=load_model(),
            session_manager=(
                get_memory_session_manager(
                    session_id,
                    user_id,
                )
            ),
            system_prompt=SYSTEM_PROMPT,
            tools=tools,
        )

    return _agents[key]
```

這樣可以避免：

```text
不同 User
卻重用第一次建立的 Session Manager
```

正式系統不建議只有一個全域 `_agent`。

---

# 13. Step 8：部署 Gateway 與 Runtime

執行：

```powershell
agentcore deploy -y -v
```

這次部署會同時處理：

- AgentCore Gateway
- WarrantyCheck Lambda Target
- Gateway IAM Role
- Lambda Invoke 權限
- 更新 CustomerSupport Runtime
- 注入 Gateway URL
- 更新 Agent 程式

第一次建立 Gateway 可能需要約數分鐘。

---

# 14. Step 9：測試 Warranty Tool

## Windows PowerShell

建立 Session：

```powershell
$SESSION_C = [guid]::NewGuid().ToString()
```

測試過期保固：

```powershell
agentcore invoke `
  "Check the warranty for product PROD-003" `
  --session-id $SESSION_C `
  -H "X-Amzn-Bedrock-AgentCore-Runtime-Custom-User-Id: Sarah" `
  --stream
```

預期回答包含：

```text
Product：Laptop Stand
Warranty Duration：6 months
Status：Expired
Expiration Date：2026-01-01
```

---

## 14.1 測試有效保固

```powershell
agentcore invoke `
  "Is the warranty still valid for PROD-002?" `
  --session-id $SESSION_C `
  -H "X-Amzn-Bedrock-AgentCore-Runtime-Custom-User-Id: Sarah" `
  --stream
```

預期結果：

```text
PROD-002 Smart Watch
Warranty Status：Active
Expiration Date：2028-01-15
```

---

# 15. 實際呼叫流程

```text
使用者：
Check warranty for PROD-003
    ↓
CustomerSupport Runtime
    ↓
Strands Agent 分析問題
    ↓
Agent 發現 check_warranty Tool
    ↓
Gateway MCP Client
    ↓
AgentCore Gateway
    ↓
WarrantyCheck Target
    ↓
workshop-warranty-check Lambda
    ↓
Lambda 回傳保固資料
    ↓
Gateway 回傳 Tool Result
    ↓
Agent 整理成自然語言回答
```

---

# 16. Lab 3 前後差異

## Lab 1～2

```text
Agent
├── main.py 本機 Tool
└── Exa AI MCP
```

特性：

- Tool 寫死在 Agent 程式
- Tool 不容易共用
- 權限管理分散
- 既有 Lambda 無法直接被 Agent 發現

---

## Lab 3

```text
Agent
├── 本機 Tool
├── Exa AI MCP
└── AgentCore Gateway
    └── Lambda Tool
```

特性：

- 既有 Lambda 不需修改
- 多個 Agent 可共用 Tool
- Gateway 統一處理 Discovery
- Gateway 統一處理 Routing
- Gateway 可集中管理驗證與權限
- 同一 Gateway 可放多種 Target

---

# 17. AgentCore Gateway 的角色

Gateway 主要負責：

```text
Tool Discovery
Tool Routing
Authentication
Target Integration
MCP Protocol
Centralized Management
```

它不是執行模型的地方。

模型仍由：

```text
Amazon Bedrock
```

提供。

Agent 仍由：

```text
AgentCore Runtime
```

執行。

Gateway 專門管理：

```text
Agent 要使用的 Tools
```

---

# 18. 常見錯誤排查

## 18.1 `$WARRANTY_LAMBDA_ARN` 是空的

檢查：

```powershell
Write-Host $WARRANTY_LAMBDA_ARN
```

可能原因：

- SSM Parameter 不存在
- Region 錯誤
- Credential 過期
- 沒有 `ssm:GetParameter`

---

## 18.2 Schema 部署失敗

檢查：

```json
"inputSchema": {
  "type": "object"
}
```

不要加額外的：

```json
"json"
```

Wrapper。

---

## 18.3 Gateway URL 沒有注入

檢查 Gateway 是否用：

```powershell
--runtimes CustomerSupport
```

建立。

並確認已重新部署：

```powershell
agentcore deploy -y -v
```

環境變數名稱應為：

```text
AGENTCORE_GATEWAY_MY_GATEWAY_URL
```

---

## 18.4 Agent 沒有呼叫 Warranty Tool

檢查：

- `warranty_schema.json` 的 Description 是否清楚
- Gateway Target 是否部署成功
- MCP Client 是否加入 `mcp_clients`
- `get_gateway_mcp_client()` 是否回傳 Client
- Runtime 是否有 Gateway URL
- Prompt 是否包含 Product ID
- Trace 是否有顯示 `check_warranty`

---

## 18.5 Lambda 回傳 404

可能原因：

- Product ID 拼錯
- Lambda 資料中沒有該商品
- Agent 傳錯參數
- Schema Parameter 名稱不是 `product_id`

---

## 18.6 AccessDenied

可能缺少：

- Lambda Invoke 權限
- Gateway 管理權限
- IAM Role 建立權限
- CloudFormation 權限
- AgentCore Gateway 權限

---

## 18.7 本機 `agentcore dev` 看不到 Gateway Tool

這通常是正常的。

因為 Gateway URL 由部署後的 AgentCore Runtime 注入：

```text
AGENTCORE_GATEWAY_MY_GATEWAY_URL
```

本機若沒有手動設定該環境變數：

```python
get_gateway_mcp_client()
```

會回傳：

```python
None
```

完整 Gateway 測試應在部署後使用：

```powershell
agentcore invoke
```

---

# 19. 完整操作順序

```text
Step 1
確認 Warranty Lambda
    ↓
Step 2
從 SSM Parameter Store 取得 Lambda ARN
    ↓
Step 3
建立 warranty_schema.json
    ↓
Step 4
agentcore add gateway
    ↓
Step 5
agentcore add gateway-target
    ↓
Step 6
在 client.py 加入 Gateway MCP Client
    ↓
Step 7
在 main.py 加入 Gateway Client
    ↓
Step 8
保留本機 Tools 與 Exa MCP
    ↓
Step 9
agentcore deploy -y -v
    ↓
Step 10
建立新的 Session ID
    ↓
Step 11
agentcore invoke 查詢保固
    ↓
Step 12
確認 Trace 呼叫 check_warranty
```

---

# 20. 指令速查表

| 指令 | 用途 |
|---|---|
| `aws ssm get-parameter` | 取得 Warranty Lambda ARN |
| `agentcore add gateway` | 建立 Gateway 設定 |
| `agentcore add gateway-target` | 將 Lambda 加入 Gateway |
| `agentcore deploy -y -v` | 部署 Gateway、Target 與 Runtime |
| `[guid]::NewGuid()` | 建立 Session UUID |
| `agentcore invoke` | 呼叫部署後 Agent |
| `-H` | 傳入 Custom User ID Header |

---

# 21. 最後檢查清單

- [ ] Lab 1 已完成
- [ ] Lab 2 已完成
- [ ] Warranty Lambda 存在
- [ ] Lambda ARN 已取得
- [ ] `tool/` 目錄已建立
- [ ] `warranty_schema.json` 格式正確
- [ ] `inputSchema` 沒有 `json` Wrapper
- [ ] `my-gateway` 已加入
- [ ] `WarrantyCheck` Target 已加入
- [ ] `client.py` 已加入 Gateway MCP Client
- [ ] `main.py` 已加入 Gateway Client
- [ ] 本機 Tools 仍保留
- [ ] Exa AI MCP 仍保留
- [ ] AgentCore Memory 仍保留
- [ ] `agentcore deploy -y -v` 成功
- [ ] Gateway URL 已注入 Runtime
- [ ] `PROD-003` 查詢成功
- [ ] `PROD-002` 查詢成功
- [ ] Trace 顯示 `check_warranty`

---

# 22. 一句話總結

本 Lab 的核心流程是：

```text
既有 Lambda
→ 撰寫 Tool Schema
→ 加入 AgentCore Gateway
→ 暴露成 MCP Tool
→ Agent 透過 Gateway 發現並呼叫
```

也就是把原本屬於其他系統的商業功能，轉換成可由多個 Agent 共用、集中管理的企業級 Tool。
