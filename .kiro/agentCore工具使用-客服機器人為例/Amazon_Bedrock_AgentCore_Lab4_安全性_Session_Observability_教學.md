# Amazon Bedrock AgentCore Lab 4：安全性、Session 與 Observability

## 0. 本 Lab 要完成什麼？

在前面的 Lab 中，你已經完成：

- Lab 1：建立 Customer Support Agent
- Lab 2：加入 AgentCore Memory
- Lab 3：使用 AgentCore Gateway 集中管理 Tool

本 Lab 會把目前的 Agent 進一步整理成較接近正式環境的架構，主要完成四件事：

1. 確認 Runtime、Memory 與 Gateway 部署狀態
2. 測試 Session Continuity 與 Session Isolation
3. 使用 CLI 與 CloudWatch 查看 Trace、Log 與 Metrics
4. 使用 Amazon Cognito JWT 保護 Runtime 與 Gateway

完成後的整體架構：

```text
Client
  │
  │ Bearer JWT
  ▼
Amazon Cognito
  │
  ▼
AgentCore Runtime
  ├── Session Management
  ├── AgentCore Memory
  ├── Local Tools
  ├── Exa AI MCP
  └── AgentCore Gateway MCP
          │
          ▼
      Warranty Lambda

CloudWatch
  ├── Traces
  ├── Logs
  └── Metrics
```

---

# 1. 前置條件

開始前請確認：

- 已完成 Lab 1～3
- `CustomerSupport` Runtime 已部署
- `SharedMemory` 已部署
- Gateway 已部署
- Warranty Lambda Target 可正常使用
- AWS Credential 尚未過期
- Region 設定正確
- Terminal 位於 `CustomerSupport` 專案根目錄

---

# 2. Step 1：確認部署狀態

執行：

```powershell
agentcore status
```

預期看到：

```text
Agents
  CustomerSupport: Deployed - Runtime: READY

Memories
  SharedMemory: Deployed

Gateways
  my-gateway: Deployed
```

確認三類資源：

| 資源 | 預期狀態 |
|---|---|
| AgentCore Runtime | `READY` |
| AgentCore Memory | `Deployed` |
| AgentCore Gateway | `Deployed` |

如果某項不是 Ready，先不要繼續做 JWT 設定，否則問題會堆疊，最後只剩一團很有雲端感的錯誤訊息。

---

# 3. Step 2：理解 Session Continuity

AgentCore Runtime 使用：

```text
session_id
```

區分每一段對話。

同一個 `session_id`：

```text
保留同一段對話上下文
```

不同 `session_id`：

```text
建立完全獨立的對話上下文
```

---

## 3.1 Session ID 基本規則

工作坊要求 Session ID 至少 33 個字元。

最簡單的方式是使用 UUID：

```powershell
$SESSION_1 = [guid]::NewGuid().ToString()
```

UUID 通常符合長度要求。

---

# 4. Step 3：測試同一個 Session

建立第一個 Session：

```powershell
$SESSION_1 = [guid]::NewGuid().ToString()
```

告訴 Agent：

```powershell
agentcore invoke `
  "My name is Carlos and I just bought a Mechanical Keyboard" `
  --session-id $SESSION_1 `
  -H "X-Amzn-Bedrock-AgentCore-Runtime-Custom-User-Id: Carlos" `
  --stream
```

接著使用相同 Session：

```powershell
agentcore invoke `
  "What did I just buy?" `
  --session-id $SESSION_1 `
  -H "X-Amzn-Bedrock-AgentCore-Runtime-Custom-User-Id: Carlos" `
  --stream
```

預期結果：

```text
Mechanical Keyboard
```

原因：

```text
相同 session_id
→ 相同 Session Context
→ 能延續剛才的對話
```

---

# 5. Step 4：測試不同 Session 的隔離

建立另一個 Session：

```powershell
$SESSION_2 = [guid]::NewGuid().ToString()
```

使用另一個 User ID：

```powershell
agentcore invoke `
  "What did I just buy?" `
  --session-id $SESSION_2 `
  -H "X-Amzn-Bedrock-AgentCore-Runtime-Custom-User-Id: JohnDoe" `
  --stream
```

預期結果：

```text
Agent 不知道 JohnDoe 剛才買了什麼
```

原因：

```text
不同 session_id
＋
不同 user_id
→ 完全獨立的 Session 與 Memory Scope
```

---

# 6. Session 與 Memory 的差異

這兩個概念很容易混在一起。

## Session Continuity

```text
同一個 session_id
→ 保留當次對話歷史
```

例如：

```text
第一句：我買了一個鍵盤
第二句：我剛才買了什麼？
```

---

## Cross-Session Memory

```text
不同 session_id
＋
相同 user_id
→ 可透過 Semantic Memory 取得長期事實
```

例如：

```text
Session A：
我叫 Carlos，我偏好 Email 通知

Session B：
你記得我的偏好嗎？
```

---

## 對照表

| 情況 | Session History | Semantic Memory |
|---|---:|---:|
| 相同 Session ID | 可用 | 可用 |
| 不同 Session、相同 User | 不共享當次對話 | 可取回長期事實 |
| 不同 Session、不同 User | 不共享 | 不應共享 |

---

# 7. Step 5：查看 Observability

AgentCore Runtime 會自動產生：

- Trace
- Log
- Metrics
- Tool Calling 紀錄
- Memory 操作紀錄
- Gateway 呼叫紀錄
- 延遲資訊

---

## 7.1 列出最近 Trace

```powershell
agentcore traces list --limit 10
```

---

## 7.2 下載指定 Trace

```powershell
agentcore traces get <trace-id> --output trace.json
```

例如：

```powershell
agentcore traces get abc123 --output trace.json
```

可以用來分析：

- 使用者 Prompt
- 模型判斷
- Tool Selection
- Tool Input
- Tool Output
- Memory Retrieval
- Gateway Invocation
- 最終 Response
- 每個步驟延遲

---

## 7.3 串流查看 Logs

```powershell
agentcore logs
```

---

## 7.4 查看最近一小時的錯誤

```powershell
agentcore logs --since 1h --level error
```

---

## 7.5 搜尋特定關鍵字

```powershell
agentcore logs --since 1h --query "warranty"
```

適合檢查：

- Warranty Lambda 是否被呼叫
- Gateway 是否連線成功
- 是否有 Tool Error
- 是否有 Authorization Error

---

# 8. Step 6：在 CloudWatch 查看 Agent

進入 AWS CloudWatch Console。

依序查看：

```text
GenAI Observability
→ Bedrock AgentCore
→ Agents
→ CustomerSupport
```

可以查看：

- Sessions
- Traces
- Logs
- Metrics
- Tool Calls
- Memory Operations
- Gateway Calls

---

## Trace 通常包含

```text
User Prompt
    ↓
Agent Reasoning / Tool Selection
    ↓
Memory Retrieval
    ↓
Tool Execution
    ↓
Gateway Invocation
    ↓
Model Response
```

> 第一次產生 Trace 後，CloudWatch 可能需要數分鐘才會顯示資料。

---

# 9. Step 7：取得 Cognito 設定

本 Lab 使用工作坊預先建立的 Cognito User Pool。

從 SSM Parameter Store 取得設定。

```powershell
$COGNITO_DISCOVERY_URL = aws ssm get-parameter `
  --name "/app/customersupport/agentcore/cognito_discovery_url" `
  --query "Parameter.Value" `
  --output text
```

```powershell
$COGNITO_CLIENT_ID = aws ssm get-parameter `
  --name "/app/customersupport/agentcore/client_id" `
  --query "Parameter.Value" `
  --output text
```

```powershell
$COGNITO_POOL_ID = aws ssm get-parameter `
  --name "/app/customersupport/agentcore/pool_id" `
  --query "Parameter.Value" `
  --output text
```

```powershell
$COGNITO_WEB_CLIENT_ID = aws ssm get-parameter `
  --name "/app/customersupport/agentcore/web_client_id" `
  --query "Parameter.Value" `
  --output text
```

確認：

```powershell
Write-Host "Discovery URL: $COGNITO_DISCOVERY_URL"
Write-Host "Client ID:     $COGNITO_CLIENT_ID"
Write-Host "Pool ID:       $COGNITO_POOL_ID"
Write-Host "Web Client ID: $COGNITO_WEB_CLIENT_ID"
```

---

# 10. Step 8：保護 AgentCore Runtime

開啟：

```text
agentcore/agentcore.json
```

在 `CustomerSupport` Runtime 中加入：

```json
"requestHeaderAllowlist": [
  "X-Amzn-Bedrock-AgentCore-Runtime-Custom-User-Id",
  "Authorization"
],
"authorizerType": "CUSTOM_JWT",
"authorizerConfiguration": {
  "customJwtAuthorizer": {
    "discoveryUrl": "<COGNITO_DISCOVERY_URL>",
    "allowedClients": [
      "<COGNITO_CLIENT_ID>",
      "<COGNITO_WEB_CLIENT_ID>"
    ]
  }
}
```

完整概念：

```json
{
  "runtimes": [
    {
      "name": "CustomerSupport",
      "build": "CodeZip",
      "entrypoint": "main.py",
      "codeLocation": "app/CustomerSupport/",
      "runtimeVersion": "PYTHON_3_13",
      "networkMode": "PUBLIC",
      "protocol": "HTTP",
      "requestHeaderAllowlist": [
        "X-Amzn-Bedrock-AgentCore-Runtime-Custom-User-Id",
        "Authorization"
      ],
      "authorizerType": "CUSTOM_JWT",
      "authorizerConfiguration": {
        "customJwtAuthorizer": {
          "discoveryUrl": "<COGNITO_DISCOVERY_URL>",
          "allowedClients": [
            "<COGNITO_CLIENT_ID>",
            "<COGNITO_WEB_CLIENT_ID>"
          ]
        }
      }
    }
  ]
}
```

請用實際值替換：

```text
<COGNITO_DISCOVERY_URL>
<COGNITO_CLIENT_ID>
<COGNITO_WEB_CLIENT_ID>
```

---

# 11. JWT Authorizer 的作用

## `discoveryUrl`

指向 Cognito OIDC Discovery Endpoint。

Runtime 會透過它取得：

- Issuer
- Signing Key URL
- Token 驗證規則
- 支援演算法

---

## `allowedClients`

限制只有特定 Cognito App Client 簽發的 Token 可以使用。

即使 Token 來自同一個 User Pool，只要 Client 不在 Allowlist，也會被拒絕。

---

## `Authorization` Header Allowlist

Runtime 要把：

```text
Authorization: Bearer <JWT>
```

傳入 Agent 程式，就必須把 `Authorization` 加入：

```json
requestHeaderAllowlist
```

---

# 12. Step 9：從 JWT 取得 User ID

正式環境不應讓使用者自己指定：

```text
X-Amzn-Bedrock-AgentCore-Runtime-Custom-User-Id
```

因為任何人都可能把自己寫成：

```text
Carlos
Sarah
Admin
```

正式做法應從已驗證的 JWT Claims 取得使用者身分。

---

## 12.1 安裝 JWT 套件

確認 `pyproject.toml` 中包含可提供 `jwt` Module 的套件，例如：

```text
PyJWT
```

修改依賴後執行：

```powershell
uv sync
```

---

## 12.2 加入 Import

```python
import jwt
```

---

## 12.3 加入 `extract_user_id`

```python
def extract_user_id(context) -> str | None:
    """從 JWT 或舊版 Custom Header 取得 user_id."""

    headers = context.request_headers or {}

    auth_header = (
        headers.get("Authorization")
        or headers.get("authorization")
    )

    if auth_header and auth_header.startswith("Bearer "):
        try:
            token = auth_header.split(" ", 1)[1]

            claims = jwt.decode(
                token,
                options={
                    "verify_signature": False
                },
            )

            username = claims.get("username")

            if username:
                return username

        except Exception as exc:
            log.warning(
                f"Failed to decode JWT: {exc}"
            )

    return headers.get(
        "x-amzn-bedrock-agentcore-runtime-custom-user-id"
    )
```

---

# 13. 安全提醒：為什麼程式裡不驗證 JWT Signature？

範例使用：

```python
jwt.decode(
    token,
    options={"verify_signature": False},
)
```

這段程式只是從 Token 中讀取 Claims。

真正的 Token 驗證應由：

```text
AgentCore Runtime CUSTOM_JWT Authorizer
```

在請求進入 Agent 程式前完成。

因此程式中的 Decode 只是：

```text
讀取已被 Runtime 驗證過的 Token 內容
```

不是自行完成安全驗證。

> 正式系統不應在沒有前置 Authorizer 的情況下，相信 `verify_signature=False` 解出的 Claims。

---

# 14. Step 10：更新 `invoke`

```python
@app.entrypoint
async def invoke(payload, context):
    log.info("Invoking Agent...")

    session_id = context.session_id
    user_id = extract_user_id(context)

    if not session_id or not user_id:
        raise ValueError(
            "session_id and user_id are required."
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

# 15. Step 11：驗證與部署 Runtime JWT

先驗證設定：

```powershell
agentcore validate
```

通過後部署：

```powershell
agentcore deploy -y -v
```

如果 `agentcore.json` 有：

- 少逗號
- JSON 格式錯誤
- Discovery URL 格式錯誤
- 不支援的欄位

`agentcore validate` 應先指出問題。

---

# 16. Step 12：建立 Cognito 測試使用者

建立使用者：

```powershell
aws cognito-idp admin-create-user `
  --user-pool-id $COGNITO_POOL_ID `
  --username "workshopuser@example.com" `
  --temporary-password "TempPass1!" `
  --user-attributes `
    "Name=email,Value=workshopuser@example.com" `
    "Name=email_verified,Value=true" `
  --message-action SUPPRESS
```

設定永久密碼：

```powershell
aws cognito-idp admin-set-user-password `
  --user-pool-id $COGNITO_POOL_ID `
  --username "workshopuser@example.com" `
  --password "WorkshopPass1!" `
  --permanent
```

確認：

```powershell
Write-Host `
  "User workshopuser@example.com created and confirmed"
```

---

# 17. Step 13：取得 Cognito Access Token

```powershell
$TOKEN = aws cognito-idp initiate-auth `
  --auth-flow USER_PASSWORD_AUTH `
  --client-id $COGNITO_WEB_CLIENT_ID `
  --auth-parameters `
    "USERNAME=workshopuser@example.com,PASSWORD=WorkshopPass1!" `
  --query "AuthenticationResult.AccessToken" `
  --output text
```

確認：

```powershell
Write-Host "Token obtained successfully"
```

不要把完整 Token 貼到公開地方。

---

# 18. Step 14：測試受保護的 Runtime

建立 Session：

```powershell
$SESSION_3 = [guid]::NewGuid().ToString()
```

帶入 Token：

```powershell
agentcore invoke `
  "What's the return policy for electronics?" `
  --session-id $SESSION_3 `
  --bearer-token "$TOKEN" `
  --stream
```

預期正常回應。

---

## 18.1 測試沒有 Token

```powershell
agentcore invoke `
  "What's the return policy for electronics?" `
  --session-id $SESSION_3 `
  --stream `
  --json
```

預期：

```text
Authentication Error
Unauthorized
401
```

這代表 Runtime 已成功受 JWT 保護。

---

# 19. Step 15：為什麼 Gateway 也要保護？

Runtime 與 Gateway 是兩個不同 Endpoint。

只保護 Runtime：

```text
Client → Runtime：有保護
Client → Gateway：仍可能直接存取
```

因此應讓 Gateway 也使用 Cognito JWT。

完整安全鏈：

```text
Client
  │ JWT
  ▼
Runtime JWT Authorizer
  │ 同一個 JWT
  ▼
Gateway JWT Authorizer
  │
  ▼
Lambda Tool
```

---

# 20. Step 16：移除舊 Gateway

工作坊指出 Gateway Authorizer 無法直接原地更新，因此先移除：

```powershell
agentcore remove gateway `
  --name my-gateway `
  -y
```

> 移除設定後，通常還需要部署，才能讓雲端資源真正被移除或更新。

---

# 21. Step 17：建立安全版 Gateway

```powershell
agentcore add gateway `
  --name my-gateway-secure `
  --runtimes CustomerSupport `
  --authorizer-type CUSTOM_JWT `
  --discovery-url $COGNITO_DISCOVERY_URL `
  --allowed-clients "$COGNITO_CLIENT_ID,$COGNITO_WEB_CLIENT_ID"
```

新的 Gateway 名稱：

```text
my-gateway-secure
```

因此部署後注入的環境變數會改成：

```text
AGENTCORE_GATEWAY_MY_GATEWAY_SECURE_URL
```

---

# 22. Step 18：重新取得 Lambda ARN

如果 Terminal 已重開，先重新取得：

```powershell
$WARRANTY_LAMBDA_ARN = aws ssm get-parameter `
  --name "/app/customersupport/agentcore/warranty_check_lambda_arn" `
  --query "Parameter.Value" `
  --output text
```

---

# 23. Step 19：重新加入 Gateway Target

```powershell
agentcore add gateway-target `
  --type lambda-function-arn `
  --name WarrantyCheck `
  --lambda-arn $WARRANTY_LAMBDA_ARN `
  --tool-schema-file app\CustomerSupport\tool\warranty_schema.json `
  --gateway my-gateway-secure
```

---

# 24. Step 20：修改 Gateway MCP Client

開啟：

```text
app/CustomerSupport/mcp_client/client.py
```

修改為：

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


def get_gateway_mcp_client(
    auth_header: str,
) -> MCPClient | None:
    """建立帶 JWT 的 AgentCore Gateway MCP Client."""

    url = os.environ.get(
        "AGENTCORE_GATEWAY_MY_GATEWAY_SECURE_URL"
    )

    if not url:
        logger.warning(
            "Gateway URL not set. "
            "Gateway tools are unavailable."
        )
        return None

    return MCPClient(
        lambda: streamablehttp_client(
            url=url,
            headers={
                "Authorization": auth_header
            },
        )
    )
```

---

# 25. 為什麼 Gateway Client 要每次請求建立？

JWT Token 是每個使用者、每次登入取得的。

如果程式啟動時只建立一次：

```python
gateway_client = get_gateway_mcp_client(...)
```

可能會把第一個使用者的 Token 固定下來。

所以安全版做法應在每個 Request 內：

```text
取得當次 Authorization Header
→ 建立當次 Gateway MCP Client
→ 將相同 JWT 轉送給 Gateway
```

---

# 26. Step 21：修改 Agent 建立流程

概念：

```python
def get_or_create_agent(
    session_id,
    user_id,
    auth_header,
):
    session_manager = get_memory_session_manager(
        session_id,
        user_id,
    )

    mcp_clients = [
        get_streamable_http_mcp_client(),
        get_gateway_mcp_client(auth_header),
    ]

    tools = [
        get_return_policy,
        get_product_info,
    ]

    for mcp_client in mcp_clients:
        if mcp_client:
            tools.append(mcp_client)

    return Agent(
        model=load_model(),
        session_manager=session_manager,
        system_prompt=SYSTEM_PROMPT,
        tools=tools,
    )
```

---

# 27. 重要提醒：不要再使用單一全域 `_agent`

工作坊範例仍使用：

```python
_agent = None
```

但安全版 Gateway Client 綁定的是當次 JWT。

如果只建立一次全域 Agent：

```text
第一個使用者的 Token
可能被後續使用者重用
```

這不只是 Session 問題，也可能變成身分隔離問題。

建議至少使用：

```python
_agents = {}


def get_or_create_agent(
    session_id: str,
    user_id: str,
    auth_header: str,
):
    key = (
        session_id,
        user_id,
    )

    if key not in _agents:
        session_manager = (
            get_memory_session_manager(
                session_id,
                user_id,
            )
        )

        mcp_clients = [
            get_streamable_http_mcp_client(),
            get_gateway_mcp_client(auth_header),
        ]

        tools = [
            get_return_policy,
            get_product_info,
        ]

        for mcp_client in mcp_clients:
            if mcp_client:
                tools.append(mcp_client)

        _agents[key] = Agent(
            model=load_model(),
            session_manager=session_manager,
            system_prompt=SYSTEM_PROMPT,
            tools=tools,
        )

    return _agents[key]
```

更嚴謹的正式系統還要考慮：

- Token 更新
- Session 過期
- Cache 清理
- 多執行個體
- User / Session 隔離
- Token 不應長期保存在全域物件

---

# 28. Step 22：從 Request Header 取得 JWT

```python
@app.entrypoint
async def invoke(payload, context):
    log.info("Invoking Agent...")

    session_id = context.session_id
    request_headers = context.request_headers or {}

    auth_header = (
        request_headers.get("Authorization")
        or request_headers.get("authorization")
    )

    if not auth_header:
        raise ValueError(
            "No Authorization header."
        )

    user_id = extract_user_id_from_token(
        auth_header
    )

    if not session_id or not user_id:
        raise ValueError(
            "session_id and user_id are required."
        )

    agent = get_or_create_agent(
        session_id,
        user_id,
        auth_header,
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

# 29. 建議的 JWT User ID 解析函式

```python
def extract_user_id_from_token(
    auth_header: str,
) -> str | None:
    """從已通過 Runtime Authorizer 的 JWT 讀取 username."""

    if not auth_header.startswith("Bearer "):
        return None

    try:
        token = auth_header.split(" ", 1)[1]

        claims = jwt.decode(
            token,
            options={
                "verify_signature": False
            },
        )

        return (
            claims.get("username")
            or claims.get("sub")
        )

    except Exception as exc:
        log.warning(
            f"Failed to decode JWT: {exc}"
        )
        return None
```

`username` 不存在時，可考慮使用：

```text
sub
```

作為穩定使用者識別。

---

# 30. Step 23：驗證並重新部署

```powershell
agentcore validate
```

成功後：

```powershell
agentcore deploy -y -v
```

這次部署應處理：

- 移除舊 Gateway
- 建立安全版 Gateway
- 加入 Warranty Target
- 更新 Runtime
- 注入新 Gateway URL
- 更新 JWT Authorizer
- 更新 Agent 程式

---

# 31. Step 24：測試安全版 Gateway

建立 Session：

```powershell
$SESSION_E = [guid]::NewGuid().ToString()
```

呼叫 Warranty Tool：

```powershell
agentcore invoke `
  "Check the warranty for PROD-001" `
  --session-id $SESSION_E `
  --bearer-token "$TOKEN" `
  --stream
```

預期：

```text
Wireless Headphones
Warranty Status：Active
Expiration Date：2027-03-01
```

這代表：

```text
Client JWT
→ Runtime 驗證成功
→ Agent 取得 JWT
→ MCP Client 轉送 JWT
→ Gateway 驗證成功
→ Lambda 執行成功
```

---

# 32. Step 25：產生測試流量

建立 Session：

```powershell
$SESSION_D = [guid]::NewGuid().ToString()
```

測試 Return Policy：

```powershell
agentcore invoke `
  "What's the return policy for accessories?" `
  --session-id $SESSION_D `
  --bearer-token "$TOKEN" `
  --stream
```

測試 Product Tool：

```powershell
agentcore invoke `
  "Tell me about the USB-C Hub" `
  --session-id $SESSION_D `
  --bearer-token "$TOKEN" `
  --stream
```

測試 Gateway Tool：

```powershell
agentcore invoke `
  "Check the warranty for PROD-002" `
  --session-id $SESSION_D `
  --bearer-token "$TOKEN" `
  --stream
```

測試 Memory：

```powershell
agentcore invoke `
  "Do you remember my name?" `
  --session-id $SESSION_D `
  --bearer-token "$TOKEN" `
  --stream
```

完成後等待數分鐘，再到 CloudWatch 查看 Trace。

---

# 33. Token 過期處理

工作坊中的 Cognito Access Token 約 60 分鐘後過期。

重新取得：

```powershell
$TOKEN = aws cognito-idp initiate-auth `
  --auth-flow USER_PASSWORD_AUTH `
  --client-id $COGNITO_WEB_CLIENT_ID `
  --auth-parameters `
    "USERNAME=workshopuser@example.com,PASSWORD=WorkshopPass1!" `
  --query "AuthenticationResult.AccessToken" `
  --output text
```

如果重開 Terminal，也要重新取得：

```text
COGNITO_DISCOVERY_URL
COGNITO_CLIENT_ID
COGNITO_POOL_ID
COGNITO_WEB_CLIENT_ID
WARRANTY_LAMBDA_ARN
TOKEN
```

PowerShell 變數不會自動跨 Terminal 保存。

---

# 34. 完成後的架構

```text
Client
  │
  │ Authorization: Bearer JWT
  ▼
AgentCore Runtime JWT Authorizer
  │
  ├── Session Management
  ├── AgentCore Memory
  ├── Local Tool：get_return_policy
  ├── Local Tool：get_product_info
  ├── Exa AI MCP
  └── Gateway MCP Client
          │
          │ Authorization: Bearer JWT
          ▼
      AgentCore Gateway JWT Authorizer
          │
          ▼
      WarrantyCheck Lambda

CloudWatch
  ├── Runtime Trace
  ├── Tool Call
  ├── Gateway Call
  ├── Memory Operations
  ├── Logs
  └── Metrics
```

---

# 35. CLI 背後做了什麼？

執行：

```powershell
agentcore deploy
```

CLI 會：

1. 封裝 Agent 程式
2. 收集 `.venv` 依賴
3. 將部署檔上傳到 S3
4. 更新 AgentCore Runtime
5. 更新 JWT Authorizer
6. 建立或更新 Gateway
7. 更新 Gateway Target
8. 設定 IAM Role 與 Policy
9. 注入 Memory ID
10. 注入 Gateway URL
11. 啟用 OpenTelemetry Observability
12. 保存部署狀態

---

# 36. 常見錯誤排查

## 36.1 `agentcore status` 顯示非 READY

先檢查：

```powershell
agentcore logs --since 1h --level error
```

再查看 CloudFormation Events。

---

## 36.2 `Unauthorized`

檢查：

- Token 是否過期
- `--bearer-token` 是否有傳入
- Runtime Authorizer 是否部署成功
- Discovery URL 是否正確
- Allowed Client ID 是否正確
- Access Token 是否來自允許的 App Client

---

## 36.3 Agent 讀不到 Authorization Header

檢查：

```json
"requestHeaderAllowlist": [
  "Authorization"
]
```

並確認已重新部署。

程式中最好同時檢查：

```python
headers.get("Authorization")
headers.get("authorization")
```

---

## 36.4 Gateway 回傳 401 / 403

檢查：

- Gateway 是否設定 JWT Authorizer
- Gateway Client 是否帶入 Authorization Header
- 是否使用新環境變數名稱
- Token 是否過期
- Runtime 與 Gateway 是否允許同一組 Client ID

---

## 36.5 Warranty Tool 消失

檢查：

- 新 Gateway 是否有 Target
- `warranty_schema.json` 是否正確
- `AGENTCORE_GATEWAY_MY_GATEWAY_SECURE_URL` 是否存在
- `get_gateway_mcp_client()` 是否回傳 `None`
- Agent Tools 清單是否包含 Gateway MCP Client

---

## 36.6 CloudWatch 沒有 Trace

可能原因：

- 資料尚未完成索引
- 尚未產生成功請求
- 請求在 Authorizer 就被拒絕
- Region 看錯
- Agent 選錯
- Trace 需要等待數分鐘

---

## 36.7 不同使用者共用 Memory 或 Gateway Token

高機率是因為：

```python
_agent = None
```

造成單一全域 Agent 被所有請求共用。

應至少依：

```text
session_id
＋
user_id
```

建立獨立 Agent 或 Session Manager。

---

# 37. 完整操作順序

```text
Step 1
agentcore status
    ↓
Step 2
測試相同 Session
    ↓
Step 3
測試不同 Session
    ↓
Step 4
查看 Trace 與 Log
    ↓
Step 5
取得 Cognito 設定
    ↓
Step 6
設定 Runtime JWT Authorizer
    ↓
Step 7
從 JWT Claims 取得 User ID
    ↓
Step 8
agentcore validate
    ↓
Step 9
agentcore deploy
    ↓
Step 10
建立 Cognito User
    ↓
Step 11
取得 Access Token
    ↓
Step 12
測試 Runtime Authentication
    ↓
Step 13
移除舊 Gateway
    ↓
Step 14
建立安全版 Gateway
    ↓
Step 15
重新加入 Lambda Target
    ↓
Step 16
修改 Gateway MCP Client
    ↓
Step 17
將 JWT 轉送 Gateway
    ↓
Step 18
重新部署
    ↓
Step 19
測試 Warranty Tool
    ↓
Step 20
產生流量並查看 CloudWatch
```

---

# 38. 指令速查表

| 指令 | 用途 |
|---|---|
| `agentcore status` | 查看部署狀態 |
| `agentcore traces list` | 列出 Trace |
| `agentcore traces get` | 下載 Trace |
| `agentcore logs` | 查看 Runtime Log |
| `aws ssm get-parameter` | 取得 Cognito / Lambda 設定 |
| `agentcore validate` | 驗證 AgentCore 設定 |
| `agentcore deploy -y -v` | 部署所有更新 |
| `aws cognito-idp admin-create-user` | 建立測試使用者 |
| `aws cognito-idp admin-set-user-password` | 設定永久密碼 |
| `aws cognito-idp initiate-auth` | 取得 Access Token |
| `agentcore remove gateway` | 移除舊 Gateway |
| `agentcore add gateway` | 建立安全 Gateway |
| `agentcore add gateway-target` | 加入 Lambda Target |
| `--bearer-token` | 帶入 JWT Token |

---

# 39. 最後檢查清單

- [ ] Runtime 狀態為 READY
- [ ] Memory 已部署
- [ ] Gateway 已部署
- [ ] 相同 Session 能延續對話
- [ ] 不同 Session 能隔離對話
- [ ] Trace 可以查詢
- [ ] Log 可以查詢
- [ ] CloudWatch 可看到 Agent
- [ ] Cognito 設定已取得
- [ ] Runtime 已設定 CUSTOM_JWT
- [ ] Authorization 已加入 Header Allowlist
- [ ] Cognito User 已建立
- [ ] Access Token 可取得
- [ ] 無 Token 時 Runtime 會拒絕
- [ ] 舊 Gateway 已移除
- [ ] 安全版 Gateway 已建立
- [ ] Warranty Target 已重新加入
- [ ] Gateway MCP Client 會轉送 JWT
- [ ] Warranty Tool 可正常使用
- [ ] CloudWatch 可看到 Tool 與 Gateway Trace
- [ ] 沒有使用單一全域 Agent 共用所有使用者

---

# 40. 一句話總結

本 Lab 的核心是：

```text
用 Session ID 隔離對話
→ 用 Memory 維持長期事實
→ 用 CloudWatch 觀察 Agent 行為
→ 用 Cognito JWT 保護 Runtime
→ 將同一個 JWT 傳給 Gateway
→ 建立端到端安全的 Agent 架構
```
