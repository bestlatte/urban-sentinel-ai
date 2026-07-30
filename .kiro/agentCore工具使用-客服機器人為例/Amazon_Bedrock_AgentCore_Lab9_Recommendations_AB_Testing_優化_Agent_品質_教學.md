# Amazon Bedrock AgentCore Lab 9：使用 Recommendations 與 A/B Testing 優化 Agent 品質

## 0. 本 Lab 要完成什麼？

前面的 Lab 已經完成：

- Lab 1：建立 Agent Prototype
- Lab 2：加入 Persistent Memory
- Lab 3：使用 AgentCore Gateway 集中管理 Tool
- Lab 4：加入 Cognito JWT、Session 與 Observability
- Lab 5：加入持續品質評估
- Lab 6：建立 Flask Chat Interface
- Lab 7：使用 Cedar Policy 管理 Tool 權限
- Lab 8：建立 Zero-Code Harness Agent

本 Lab 會使用 **AgentCore Optimization**，把既有的：

```text
CloudWatch Traces
＋
Evaluation Scores
```

轉換成可執行的改善建議，並透過 A/B Testing 驗證改善是否真的有效。

完整流程：

```text
分析正式互動 Trace
    ↓
產生 System Prompt 或 Tool Description 建議
    ↓
建立 Control / Treatment Config Bundle
    ↓
Gateway 分流正式測試流量
    ↓
Online Evaluation 評估兩個版本
    ↓
查看統計顯著性
    ↓
Promote 勝出版本
    ↓
開始下一輪改善
```

---

# 1. Public Preview 注意事項

AgentCore Optimization 目前屬於：

```text
Public Preview
```

這代表：

- CLI 指令可能改變
- Config Schema 可能改變
- A/B Test 行為可能調整
- Recommendation 是由 LLM 產生
- 建議不應未經測試就直接上線

必須遵守：

```text
Recommendation
≠ 已證明有效的改善
```

正確流程是：

```text
產生建議
→ 人工審查
→ A/B Test
→ 查看統計結果
→ 再決定是否採用
```

---

# 2. 本 Lab 的優化循環

AgentCore Optimization 使用四個階段：

## 2.1 Generate Recommendation

輸入：

- 真實 Agent Trace
- 現有 System Prompt 或 Tool Description
- Target Evaluator

輸出：

- 建議的 System Prompt
- 建議的 Tool Description
- 修改原因

---

## 2.2 Package as Config Bundle

將設定封裝成：

```text
不可變更、具版本號的設定快照
```

例如：

```text
Control Bundle v1
Treatment Bundle v1
```

---

## 2.3 Validate with A/B Test

Gateway 按 Session 分流：

```text
80% → Control
20% → Treatment
```

每個 Session 綁定固定 Variant，避免同一段對話中途切換 Prompt。

---

## 2.4 Promote and Repeat

如果 Treatment 顯著較好：

```text
Promote Treatment
→ 成為新 Control
→ 收集新 Trace
→ 開始下一輪優化
```

---

# 3. 前面 Lab 提供了什麼？

| Lab | 產出 | Lab 9 的用途 |
|---|---|---|
| Lab 1 | System Prompt、Tool 定義 | 優化目標 |
| Lab 3 | AgentCore Gateway | A/B Traffic Splitter |
| Lab 4 | CloudWatch Trace | Recommendation 資料來源 |
| Lab 5 | GoalSuccessRate Evaluation | Optimization Reward Signal |

---

# 4. 前置條件

開始前請確認：

- 已完成 Lab 5
- 建議已完成 Lab 1～8
- `CustomerSupport` Runtime 已部署
- `my-gateway-secure` 已部署
- CloudWatch Transaction Search 已啟用
- `QualityMonitor` 已收集 Evaluation Data
- Cognito Token 仍有效
- AWS Credential 尚未過期
- Terminal 位於專案根目錄

---

# 5. Step 0：更新 AgentCore CLI

執行：

```powershell
agentcore update
```

確認版本：

```powershell
agentcore --version
```

因為本 Lab 使用的是 Preview Optimization 與 A/B Test 功能，舊版 CLI 可能沒有對應指令。

---

# 6. Step 1：確認 AgentCore SDK 版本

開啟：

```text
app/CustomerSupport/pyproject.toml
```

確認至少包含：

```toml
dependencies = [
    "bedrock-agentcore >= 1.8.0"
]
```

A/B Testing 的 Baggage Propagation 與：

```python
BedrockAgentCoreContext.get_config_bundle()
```

需要較新的 SDK。

修改後執行：

```powershell
cd app\CustomerSupport
uv sync
cd ..\..
```

---

# 7. Step 2：確認 CloudWatch Transaction Search

Recommendations 會從 CloudWatch 讀取 Trace。

AWS Console 路徑：

```text
CloudWatch
→ Application Signals
→ Transaction Search
```

如果 Transaction Search 沒有啟用：

```text
Recommendation Engine
可能找不到可分析的 Trace
```

---

# 8. Step 3：重新取得 Cognito Token

如果 `$TOKEN` 已過期或開了新的 Terminal，重新取得。

## 8.1 取得 Web Client ID

```powershell
$COGNITO_WEB_CLIENT_ID = aws ssm get-parameter `
  --name "/app/customersupport/agentcore/web_client_id" `
  --query "Parameter.Value" `
  --output text
```

---

## 8.2 取得 Access Token

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

不要把 Token 寫入 Git、Markdown 或公開 Log。

---

# 9. Step 4：產生可分析的 Trace

建立 Session：

```powershell
$SESSION_OPT = [guid]::NewGuid().ToString()
```

本 Lab 建議產生：

- 明確問題
- 模糊問題
- Tool 邊界問題
- Multi-Intent 問題
- 沒有提供 Product ID 的問題

---

## 9.1 明確商品問題

```powershell
agentcore invoke `
  "What's the price and battery life of the Smart Watch?" `
  --session-id $SESSION_OPT `
  --bearer-token "$TOKEN" `
  --stream
```

---

## 9.2 Return 與 Technical Support 模糊問題

```powershell
agentcore invoke `
  "My headphones are broken. What should I do?" `
  --session-id $SESSION_OPT `
  --bearer-token "$TOKEN" `
  --stream
```

這題可能讓 Agent 不確定要：

- 查退貨政策
- 查保固
- 搜尋疑難排解
- 先詢問澄清問題

---

## 9.3 Warranty 問題

```powershell
agentcore invoke `
  "Is PROD-002 still under warranty?" `
  --session-id $SESSION_OPT `
  --bearer-token "$TOKEN" `
  --stream
```

---

## 9.4 Multi-Intent 問題

```powershell
agentcore invoke `
  "I want to return my USB-C Hub and also check if it's under warranty." `
  --session-id $SESSION_OPT `
  --bearer-token "$TOKEN" `
  --stream
```

---

## 9.5 資訊不足的模糊問題

```powershell
agentcore invoke `
  "It stopped working. Can I get my money back?" `
  --session-id $SESSION_OPT `
  --bearer-token "$TOKEN" `
  --stream
```

---

## 9.6 等待 Trace 進入 CloudWatch

```powershell
Start-Sleep -Seconds 300
```

工作坊建議等待約：

```text
2～5 分鐘
```

Recommendation Engine 讀的是 CloudWatch Logs 中已完成收錄的 Trace。

---

# 10. Step 5：產生 System Prompt Recommendation

執行：

```powershell
agentcore run recommendation `
  --type system-prompt `
  --run cs-prompt-rec `
  --runtime CustomerSupport `
  --evaluator Builtin.GoalSuccessRate `
  --inline "You are a helpful and professional customer support assistant for an e-commerce company. Provide accurate information using the tools available to you. Be friendly, patient, and understanding. Always offer additional help after answering. Always use tools to get accurate information rather than guessing." `
  --lookback 7 `
  --wait
```

---

## 10.1 參數說明

| 參數 | 用途 |
|---|---|
| `--type system-prompt` | 優化 System Prompt |
| `--run cs-prompt-rec` | Recommendation Job 名稱 |
| `--runtime CustomerSupport` | 指定 Trace 所屬 Runtime |
| `--evaluator` | 最佳化的目標分數 |
| `--inline` | 現有 System Prompt |
| `--lookback 7` | 分析最近 7 天 Trace |
| `--wait` | 等待 Job 完成 |

---

## 10.2 `--wait` 的作用

有 `--wait`：

```text
CLI 會等待 Recommendation Job 完成
```

沒有 `--wait`：

```text
CLI 立即回傳 Recommendation ID
稍後再查詢結果
```

---

# 11. Step 6：查看 System Prompt 建議

```powershell
agentcore view recommendation `
  cs-prompt-rec `
  --json
```

重點欄位：

```text
recommendedSystemPrompt
explanation
```

---

## 11.1 Recommendation 可能改善什麼？

例如 Trace 顯示 Agent 對：

```text
My headphones are broken
```

經常選錯 Tool，Recommendation 可能加入：

```text
When the customer's intent is unclear between a return,
warranty issue, or technical support issue,
ask one clarifying question before selecting a tool.
```

新的 Prompt 通常應：

- 保留原始要求
- 加入 Trace 中缺少的 Guardrail
- 明確處理 Multi-Intent
- 明確處理模糊問題
- 降低猜測與錯誤 Tool Selection

---

## 11.2 保存 Treatment Prompt

把：

```text
recommendedSystemPrompt
```

保存到安全位置。

後續建立 Treatment Config Bundle 時需要使用。

建議另外建立：

```text
recommended_prompt.txt
```

避免在長指令中貼錯引號。

---

# 12. Step 7：產生 Tool Description Recommendation

執行：

```powershell
agentcore run recommendation `
  --type tool-description `
  --run cs-tool-rec `
  --runtime CustomerSupport `
  --tools "get_return_policy:Get return policy information for a specific product category (electronics, accessories, audio)." `
  --tools "get_product_info:Search for product information by name, ID (e.g. PROD-001), or keyword." `
  --tools "check_warranty:Check the warranty status of a product by its product ID. Returns duration, status, and expiration date." `
  --lookback 7 `
  --wait
```

---

## 12.1 為什麼不需要 `--evaluator`？

System Prompt Recommendation 需要目標 Evaluator。

Tool Description Recommendation 則直接分析：

- Tool Selection Trace
- Tool Confusion
- Tool Input Pattern
- Tool 邊界重疊

所以不需要額外指定 Evaluator。

---

# 13. Step 8：查看 Tool 建議

```powershell
agentcore view recommendation `
  cs-tool-rec `
  --json
```

每個 Tool 會有：

```text
toolName
recommendedToolDescription
explanation
```

---

## 13.1 常見改善方向

例如：

### 原本

```text
Check warranty status.
```

### 改善後

```text
Use this tool only when the user asks whether a product's
manufacturer warranty is active, expired, or when it expires.
Do not use it for return windows, refunds, or exchanges.
```

Tool Description 應清楚說明：

- 何時使用
- 何時不要使用
- 需要哪些輸入
- 回傳什麼
- 與其他 Tool 的界線

---

# 14. Recommendation 只是 Hypothesis

不要直接把建議貼到 Production。

Recommendation 可能：

- 改善 GoalSuccessRate
- 但降低 Correctness
- 增加不必要澄清
- 增加 Token 使用
- 造成回答變慢
- 誤解 Tool 邊界

因此必須透過：

```text
A/B Test
```

驗證。

---

# 15. 為什麼需要專用 A/B Runtime？

原本的：

```text
CustomerSupport Runtime
```

在 Lab 4 已設定：

```text
CUSTOM_JWT
```

A/B Traffic Split 發生在 Gateway。

Gateway 呼叫 HTTP Runtime Target 時使用：

```text
SigV4 / IAM
```

如果 Gateway 用 SigV4 呼叫只接受 CUSTOM_JWT 的 Runtime，會出現：

```text
Authorization method mismatch
```

所以本 Lab不修改 Production Runtime，而是建立：

```text
CustomerSupportAB
```

它保留：

```text
Default IAM Authorizer
```

架構：

```text
Client Cognito JWT
    ↓
Secure Gateway
    ↓
SigV4 / IAM
    ↓
CustomerSupportAB Runtime
```

---

# 16. Step 9：建立專用 A/B Runtime

執行：

```powershell
agentcore add agent `
  --name CustomerSupportAB `
  --language Python `
  --framework Strands `
  --model-provider Bedrock `
  --memory none `
  --build CodeZip
```

建立後會出現：

```text
app/
└── CustomerSupportAB/
    ├── main.py
    └── pyproject.toml
```

---

# 17. Step 10：修改 A/B Runtime 的 `main.py`

開啟：

```text
app/CustomerSupportAB/main.py
```

使用 Config Bundle Aware Agent：

```python
"""Dedicated A/B customer support runtime."""

from bedrock_agentcore.runtime import (
    BedrockAgentCoreApp,
    BedrockAgentCoreContext,
)
from strands import Agent, tool
from strands.hooks.events import BeforeModelCallEvent
from strands.models.bedrock import BedrockModel


app = BedrockAgentCoreApp()
log = app.logger


MODEL_ID = (
    "global.anthropic.claude-sonnet-4-5-20250929-v1:0"
)

DEFAULT_SYSTEM_PROMPT = (
    "You are a helpful and professional customer support "
    "assistant for an e-commerce company. "
    "Always use tools to get accurate information "
    "rather than guessing."
)


RETURN_POLICIES = {
    "electronics": {
        "window": "30 days",
        "condition": (
            "Original packaging required, "
            "must be unused or defective"
        ),
        "refund": (
            "Full refund to original payment method"
        ),
    },
    "accessories": {
        "window": "14 days",
        "condition": (
            "Must be in original packaging, unused"
        ),
        "refund": "Store credit or exchange",
    },
    "audio": {
        "window": "30 days",
        "condition": (
            "Defective items only after 15 days"
        ),
        "refund": (
            "Full refund within 15 days, "
            "replacement after"
        ),
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
    },
    "PROD-002": {
        "name": "Smart Watch",
        "price": 249.99,
        "category": "electronics",
        "description": (
            "Fitness tracker with heart rate monitor, "
            "GPS, and 5-day battery"
        ),
    },
    "PROD-003": {
        "name": "Laptop Stand",
        "price": 39.99,
        "category": "accessories",
        "description": (
            "Adjustable aluminum laptop stand "
            "for ergonomic desk setup"
        ),
    },
    "PROD-004": {
        "name": "USB-C Hub",
        "price": 54.99,
        "category": "accessories",
        "description": (
            "7-in-1 USB-C hub with HDMI, USB-A, "
            "SD card reader, and ethernet"
        ),
    },
    "PROD-005": {
        "name": "Mechanical Keyboard",
        "price": 129.99,
        "category": "electronics",
        "description": (
            "RGB mechanical keyboard "
            "with Cherry MX switches"
        ),
    },
}


@tool
def get_return_policy(
    product_category: str,
) -> str:
    """Get return policy for a supported product category."""

    category = product_category.lower()
    policy = RETURN_POLICIES.get(category)

    if not policy:
        return (
            f"No specific return policy found for "
            f"'{product_category}'. Please contact support."
        )

    return (
        f"Return policy for {category}: "
        f"Window: {policy['window']}, "
        f"Condition: {policy['condition']}, "
        f"Refund: {policy['refund']}"
    )


@tool
def get_product_info(query: str) -> str:
    """Search product information by name, ID, or keyword."""

    product_id = query.upper()

    if product_id in PRODUCTS:
        product = PRODUCTS[product_id]

        return (
            f"{product['name']} ({product_id}): "
            f"${product['price']}, "
            f"Category: {product['category']}, "
            f"{product['description']}"
        )

    normalized_query = query.lower()

    results = [
        (
            f"{product_id}: {product['name']} - "
            f"${product['price']} - "
            f"{product['description']}"
        )
        for product_id, product in PRODUCTS.items()
        if (
            normalized_query
            in product["name"].lower()
            or normalized_query
            in product["description"].lower()
            or normalized_query
            in product["category"].lower()
        )
    ]

    if results:
        return "Found products:\n" + "\n".join(results)

    return f"No products found matching '{query}'."


agent = Agent(
    model=BedrockModel(
        model_id=MODEL_ID
    ),
    system_prompt=DEFAULT_SYSTEM_PROMPT,
    tools=[
        get_return_policy,
        get_product_info,
    ],
)


def dynamic_config_hook(
    event: BeforeModelCallEvent,
):
    """Apply active config bundle before each model call."""

    try:
        config = (
            BedrockAgentCoreContext.get_config_bundle()
        )
    except Exception as exc:
        log.warning(
            "Could not read config bundle. "
            f"Using default prompt: {exc}"
        )
        config = {}

    event.agent.system_prompt = config.get(
        "system_prompt",
        DEFAULT_SYSTEM_PROMPT,
    )


agent.hooks.add_callback(
    BeforeModelCallEvent,
    dynamic_config_hook,
)


@app.entrypoint
def invoke(payload, context):
    result = agent(
        payload.get(
            "prompt",
            "Hello",
        )
    )

    return {
        "response": (
            result.message["content"][0]["text"]
        )
    }


if __name__ == "__main__":
    app.run()
```

---

## 17.1 Dynamic Config Hook 的作用

每次模型呼叫前：

```text
Gateway 指派 Config Bundle
    ↓
Runtime 讀取 Config Bundle
    ↓
取得 system_prompt
    ↓
套用到 Agent
```

Control 與 Treatment 可以共用同一個 Runtime Code，只改設定。

---

# 18. Step 11：更新 A/B Runtime Dependencies

開啟：

```text
app/CustomerSupportAB/pyproject.toml
```

確認：

```toml
dependencies = [
    "bedrock-agentcore >= 1.8.0",
    "strands-agents[otel] >= 1.13.0",
    "aws-opentelemetry-distro",
    "boto3"
]
```

同步：

```powershell
cd app\CustomerSupportAB
uv sync
cd ..\..
```

---

# 19. 不要替 A/B Runtime 加 CUSTOM_JWT

`CustomerSupportAB` 必須保留：

```text
IAM Authorizer
```

不要複製 Production Runtime 的：

```json
"authorizerType": "CUSTOM_JWT"
```

否則 Gateway 使用 SigV4 呼叫時仍會失敗。

安全性並沒有消失：

```text
只有具有 IAM 權限的 Gateway Execution Role
可以呼叫 CustomerSupportAB
```

---

# 20. Step 12：部署 A/B Runtime

```powershell
agentcore deploy -y -v
```

確認：

```powershell
agentcore status
```

應看到：

```text
CustomerSupportAB
```

---

# 21. Step 13：把 Gateway 指向 A/B Runtime

新增 HTTP Runtime Target：

```powershell
agentcore add gateway-target `
  --name customer-support-ab `
  --gateway my-gateway-secure `
  --type http-runtime `
  --runtime CustomerSupportAB
```

部署：

```powershell
agentcore deploy -y -v
```

Gateway Target Path 會使用：

```text
/customer-support-ab/
```

後續 Load Test 必須打這個 Target Path。

---

# 22. Step 14：建立 Control Config Bundle

```powershell
agentcore add config-bundle `
  --name customerSupportControl `
  --commit-message "Baseline prompt" `
  --components '{"{{runtime:CustomerSupportAB}}":{"configuration":{"system_prompt":"You are a helpful and professional customer support assistant for an e-commerce company. Provide accurate information using the tools available to you. Be friendly, patient, and understanding. Always offer additional help after answering. Always use tools to get accurate information rather than guessing."}}}'
```

部署：

```powershell
agentcore deploy -y -v
```

記下：

```text
Control Bundle Version ID
```

---

# 23. Step 15：建立 Treatment Config Bundle

將 Step 6 的：

```text
recommendedSystemPrompt
```

貼入 Treatment Bundle：

```powershell
agentcore add config-bundle `
  --name customerSupportTreatment `
  --commit-message "Recommended prompt from cs-prompt-rec" `
  --components '{"{{runtime:CustomerSupportAB}}":{"configuration":{"system_prompt":"<PASTE_RECOMMENDED_SYSTEM_PROMPT_HERE>"}}}'
```

部署：

```powershell
agentcore deploy -y -v
```

記下：

```text
Treatment Bundle Version ID
```

---

## 23.1 PowerShell JSON 引號注意事項

Recommended Prompt 如果包含：

- 雙引號
- 換行
- 特殊字元

直接塞進單行 JSON 容易失敗。

較安全方式是先用 PowerShell 建立物件：

```powershell
$recommendedPrompt = Get-Content `
  .\recommended_prompt.txt `
  -Raw
```

```powershell
$componentsObject = @{
  "{{runtime:CustomerSupportAB}}" = @{
    configuration = @{
      system_prompt = $recommendedPrompt
    }
  }
}
```

```powershell
$componentsJson = $componentsObject `
  | ConvertTo-Json -Depth 10 -Compress
```

再執行：

```powershell
agentcore add config-bundle `
  --name customerSupportTreatment `
  --commit-message "Recommended prompt from cs-prompt-rec" `
  --components $componentsJson
```

這樣比手動逃逸 JSON 安全。

---

# 24. Step 16：建立 A/B Runtime 專用 Online Evaluation

Lab 5 的：

```text
QualityMonitor
```

綁定 `CustomerSupport` Runtime。

它不會自動評估：

```text
CustomerSupportAB
```

因此建立：

```powershell
agentcore add online-eval `
  --name ABQualityMonitor `
  --runtime CustomerSupportAB `
  --evaluator Builtin.GoalSuccessRate `
  --sampling-rate 100 `
  --enable-on-create
```

部署：

```powershell
agentcore deploy -y -v
```

---

# 25. Step 17：建立 A/B Test

假設你已取得：

```text
Control Bundle Version ID
Treatment Bundle Version ID
```

執行：

```powershell
agentcore run ab-test `
  --mode config-bundle `
  --name cs-prompt-abtest `
  --gateway my-gateway-secure `
  --runtime CustomerSupportAB `
  --control-bundle customerSupportControl `
  --control-version <CONTROL_VERSION_ID> `
  --treatment-bundle customerSupportTreatment `
  --treatment-version <TREATMENT_VERSION_ID> `
  --online-eval ABQualityMonitor `
  --control-weight 80 `
  --treatment-weight 20
```

---

## 25.1 分流設定

```text
Control：80%
Treatment：20%
```

每個新的 Session 被分配到其中一個版本。

同一 Session：

```text
會固定使用同一 Variant
```

這稱為：

```text
Sticky Assignment
```

---

## 25.2 保存 A/B Test Job ID

CLI 會輸出類似：

```text
cs-prompt-abtest-XXXXXXXXXX
```

後續需要用在：

- View
- Pause
- Resume
- Promote
- Stop
- Archive

---

## 25.3 Gateway 限制

同一個 Gateway 同時間通常只能有：

```text
一個 Running A/B Test
```

開始新 Test 前，先確認舊 Test 是否已停止或封存。

---

# 26. Step 18：查看 A/B Test 資訊

```powershell
agentcore view ab-test `
  cs-prompt-abtest-XXXXXXXXXX
```

確認：

- Gateway
- Runtime
- Control Bundle
- Treatment Bundle
- Weight
- Invocation URL
- Test Status

---

# 27. 重要：使用正確的 Gateway Target Path

即使 `view ab-test` 顯示某個 Invocation URL，實際流量必須打到：

```text
/customer-support-ab/invocations
```

完整格式：

```text
https://<gateway-id>.gateway.bedrock-agentcore.<region>.amazonaws.com/customer-support-ab/invocations
```

不要誤打：

```text
/CustomerSupportAB/
/CustomerSupport/
/invocations
```

Target Name 來自：

```text
customer-support-ab
```

---

# 28. Step 19：Windows PowerShell 產生 A/B Traffic

先設定 Gateway URL：

```powershell
$GATEWAY_URL = "https://<gateway-id>.gateway.bedrock-agentcore.<region>.amazonaws.com/customer-support-ab/invocations"
```

準備測試 Prompt：

```powershell
$PROMPTS = @(
  "What's the price of the Smart Watch?",
  "My headphones are broken, what should I do?",
  "Is PROD-002 still under warranty?",
  "What's the return policy for audio products?",
  "It stopped working. Can I get a refund?",
  "I want to return my USB-C Hub and check its warranty."
)
```

發送 30 個不同 Session：

```powershell
for ($i = 1; $i -le 30; $i++) {
  $prompt = $PROMPTS[
    ($i - 1) % $PROMPTS.Count
  ]

  $sessionId = [guid]::NewGuid().ToString()

  Write-Host "=== Request $i ==="
  Write-Host $prompt

  $body = @{
    prompt = $prompt
  } | ConvertTo-Json -Compress

  try {
    $response = Invoke-RestMethod `
      -Uri $GATEWAY_URL `
      -Method Post `
      -Headers @{
        Authorization = "Bearer $TOKEN"
        "X-Amzn-Bedrock-AgentCore-Runtime-Session-Id" = $sessionId
      } `
      -ContentType "application/json" `
      -Body $body

    $response | ConvertTo-Json -Depth 10
  }
  catch {
    Write-Warning $_
  }

  Start-Sleep -Seconds 2
}
```

---

## 28.1 為什麼每個 Request 使用新 Session ID？

Gateway 分流是以 Session 為單位。

如果 30 次請求全部使用同一個 Session：

```text
30 次都會落在同一 Variant
```

使用不同 Session ID 才能讓：

```text
Control 與 Treatment 都獲得樣本
```

---

# 29. Step 20：等待 A/B Evaluation

A/B Result 不會立即出現。

工作坊指出，Session 完成與 Evaluation 聚合可能需要約：

```text
15 分鐘或更久
```

原因包括：

- Session Timeout
- Trace Ingestion
- Online Evaluation
- Statistical Aggregation

可以先等待：

```powershell
Start-Sleep -Seconds 900
```

---

# 30. Step 21：查看 A/B 結果

```powershell
agentcore view ab-test `
  cs-prompt-abtest-XXXXXXXXXX `
  --json
```

重點欄位：

- Control Mean
- Treatment Mean
- Percent Change
- P-Value
- Significance Flag
- Sample Count

---

# 31. 如何判讀 A/B Test？

| 結果 | 解讀 | 建議 |
|---|---|---|
| `p < 0.05` 且 `percentChange > 0` | Treatment 顯著較好 | 可考慮 Promote |
| `p < 0.05` 且 `percentChange < 0` | Treatment 顯著較差 | 保留 Control |
| `p >= 0.05` | 證據不足 | 增加樣本或延長測試 |

---

## 31.1 P-Value 是什麼？

概念上：

```text
P-Value 越小
→ 目前差異只是隨機造成的可能性越低
```

常見門檻：

```text
p < 0.05
```

但不能只看 P-Value。

還要看：

- Sample Size
- Effect Size
- Percent Change
- Correctness
- Latency
- Cost
- Failure Rate

---

## 31.2 不要只看 GoalSuccessRate

Treatment 可能：

```text
GoalSuccessRate 上升
Correctness 下降
Latency 上升
Token Cost 上升
```

正式決策應同時觀察：

- Goal Success
- Correctness
- Tool Selection
- Latency
- Cost
- Error Rate

本 Lab 的 `ABQualityMonitor` 只設定 GoalSuccessRate，是簡化版本。

---

# 32. Step 22：Promote 勝出版本

如果 Treatment 顯著勝出：

```powershell
agentcore promote ab-test `
  -i cs-prompt-abtest-XXXXXXXXXX
```

部署：

```powershell
agentcore deploy -y -v
```

Promote 會：

- 停止 Test
- 將 Treatment Version 提升
- 更新 Control Bundle
- 後續流量使用勝出版本

---

# 33. Step 23：停止失敗或無效的 Test

如果 Treatment 沒有勝出：

```powershell
agentcore stop ab-test `
  -i cs-prompt-abtest-XXXXXXXXXX
```

所有流量回到 Control。

---

## 33.1 暫停與恢復

暫停：

```powershell
agentcore pause ab-test `
  -i cs-prompt-abtest-XXXXXXXXXX
```

恢復：

```powershell
agentcore resume ab-test `
  -i cs-prompt-abtest-XXXXXXXXXX
```

適合：

- 維護期間
- Gateway 異常
- Token 問題
- 測試資料污染
- 暫時停止成本

---

# 34. Optimization 的完整架構

```text
CloudWatch Traces
    ↓
Recommendation Engine
    ↓
Optimized Prompt / Tool Description
    ↓
Control Config Bundle
Treatment Config Bundle
    ↓
Secure Gateway
    ↓
A/B Session Split
    ├── Control
    └── Treatment
          ↓
CustomerSupportAB Runtime
          ↓
ABQualityMonitor
          ↓
Statistical Result
          ↓
Promote Winner
```

Production 的：

```text
CustomerSupport Runtime
```

保持：

```text
CUSTOM_JWT
```

A/B 專用的：

```text
CustomerSupportAB
```

使用：

```text
IAM Auth
```

兩者分離，避免降低 Production Runtime 安全性。

---

# 35. Step 24：清理 A/B Test 資源

完成測試後，先停止：

```powershell
agentcore stop ab-test `
  -i cs-prompt-abtest-XXXXXXXXXX
```

再封存：

```powershell
agentcore archive ab-test `
  -i cs-prompt-abtest-XXXXXXXXXX
```

---

## 35.1 移除 Gateway Target

```powershell
agentcore remove gateway-target `
  --name customer-support-ab `
  --gateway my-gateway-secure `
  -y
```

---

## 35.2 移除 A/B Online Eval

```powershell
agentcore remove online-eval `
  ABQualityMonitor `
  -y
```

---

## 35.3 移除 A/B Runtime

```powershell
agentcore remove agent `
  CustomerSupportAB `
  -y
```

---

## 35.4 部署移除結果

```powershell
agentcore deploy -y -v
```

---

## 35.5 Config Bundle 不一定會自動刪除

刪除 A/B Test 不代表自動刪除：

- Control Config Bundle
- Treatment Config Bundle
- Gateway
- Online Eval
- Runtime

這些資源需要分別清理。

如果 CLI 參數和工作坊不一致：

```powershell
agentcore remove --help
```

Preview CLI 的指令可能改變。

---

# 36. Recommendation 與 A/B Testing 的價值

## 傳統改善方式

```text
覺得 Prompt 不夠好
→ 人工修改
→ 直接上線
→ 靠感覺判斷
```

---

## AgentCore Optimization

```text
分析真實 Trace
→ 找出失敗 Pattern
→ 產生 Recommendation
→ 建立 Versioned Bundle
→ A/B Test
→ 統計驗證
→ Promote
```

差異在於：

```text
從「猜哪個版本比較好」
變成「用實際資料證明哪個版本比較好」
```

---

# 37. 常見錯誤排查

## 37.1 Recommendation 找不到 Trace

檢查：

- Transaction Search 是否啟用
- Runtime 是否有近期互動
- `--lookback` 是否涵蓋資料
- Region 是否正確
- CloudWatch Log 是否已完成收錄

---

## 37.2 Recommendation Job 一直沒有結果

可能原因：

- Trace 太少
- Job 仍在執行
- Preview Service 延遲
- Target Evaluator 沒有資料
- IAM 權限不足

可以不使用 `--wait`，稍後再查：

```powershell
agentcore view recommendation `
  cs-prompt-rec `
  --json
```

---

## 37.3 `get_config_bundle()` 不存在

檢查：

```text
bedrock-agentcore >= 1.8.0
```

並重新：

```powershell
uv sync
```

---

## 37.4 Gateway 呼叫 Runtime 出現 Authorization Mismatch

檢查：

- 是否錯誤使用 Production `CustomerSupport`
- `CustomerSupportAB` 是否加了 CUSTOM_JWT
- Gateway Target 是否指向 `CustomerSupportAB`
- A/B Runtime 是否保留 IAM Auth

---

## 37.5 Load Test 回傳 404

高機率是 URL Path 錯誤。

應使用：

```text
/customer-support-ab/invocations
```

---

## 37.6 A/B Test 只有一邊有樣本

可能原因：

- 所有 Request 使用同一 Session ID
- 樣本太少
- Sticky Assignment 導致全部落同一 Variant
- Treatment Weight 太低

解法：

- 每次使用新 Session ID
- 增加 Request 數量
- 延長測試
- 調整 Weight

---

## 37.7 結果沒有統計顯著性

可能原因：

- 樣本太少
- Treatment 改善幅度太小
- 問題分布不穩定
- Evaluation 噪音太大

不要為了得到顯著性反覆偷看後立即停止，應先決定合理樣本與測試期間。

---

## 37.8 Config Bundle JSON 失敗

原因通常是 Prompt 中包含：

- 雙引號
- 換行
- Backslash
- 特殊字元

建議使用：

```powershell
ConvertTo-Json
```

產生 Components JSON。

---

## 37.9 Promote 後 Production Agent 沒有改變

本 Lab Promote 的是：

```text
CustomerSupportAB
```

Production：

```text
CustomerSupport
```

不會自動更新。

驗證勝出後，仍需把勝出 Prompt：

- 更新到 Production `main.py`
- 或讓 Production Runtime 也支援 Config Bundle

---

# 38. 實務上的改善建議

## 38.1 先定義成功指標

不要只有：

```text
GoalSuccessRate
```

可以加上：

- Correctness
- Tool Selection
- Latency
- Cost per Session
- Escalation Rate
- User Satisfaction
- Hallucination Rate

---

## 38.2 每次只測一個主要變因

較容易判讀：

```text
Control：舊 Prompt
Treatment：新 Prompt
```

不要同時改：

- Prompt
- Model
- Tool Description
- Temperature
- Retrieval
- Gateway Tool

否則無法知道是哪個變更造成差異。

---

## 38.3 確保流量具有代表性

測試 Prompt 應包含：

- 簡單問題
- 模糊問題
- 多意圖問題
- Tool 邊界問題
- 錯誤輸入
- 資訊不足問題

只測「漂亮問題」會得到漂亮但沒有實務價值的分數。

---

## 38.4 Recommendation 必須人工審查

檢查：

- 是否改變原始商業規則
- 是否過度增加澄清
- 是否要求不存在的 Tool
- 是否洩漏內部資訊
- 是否增加不必要 Token
- 是否與 Cedar Policy 衝突

---

# 39. 完整操作順序

```text
Step 1
更新 AgentCore CLI
    ↓
Step 2
更新 AgentCore SDK
    ↓
Step 3
確認 Transaction Search
    ↓
Step 4
取得 Cognito Token
    ↓
Step 5
產生近期 Trace
    ↓
Step 6
執行 System Prompt Recommendation
    ↓
Step 7
執行 Tool Description Recommendation
    ↓
Step 8
人工審查 Recommendation
    ↓
Step 9
建立 CustomerSupportAB Runtime
    ↓
Step 10
加入 Config Bundle Hook
    ↓
Step 11
保留 IAM Authorizer
    ↓
Step 12
Gateway 加入 HTTP Runtime Target
    ↓
Step 13
建立 Control Bundle
    ↓
Step 14
建立 Treatment Bundle
    ↓
Step 15
建立 ABQualityMonitor
    ↓
Step 16
建立 80/20 A/B Test
    ↓
Step 17
使用不同 Session 產生流量
    ↓
Step 18
等待 Evaluation
    ↓
Step 19
查看 P-Value 與 Percent Change
    ↓
Step 20
Promote 或 Stop
    ↓
Step 21
將勝出 Prompt 套用 Production
    ↓
Step 22
清理 A/B 資源
```

---

# 40. 指令速查表

| 指令 | 用途 |
|---|---|
| `agentcore update` | 更新 CLI |
| `agentcore run recommendation` | 建立 Recommendation |
| `agentcore view recommendation` | 查看 Recommendation |
| `agentcore add agent` | 建立 A/B Runtime |
| `agentcore add gateway-target` | 新增 HTTP Runtime Target |
| `agentcore add config-bundle` | 建立 Config Bundle |
| `agentcore add online-eval` | 建立 A/B Eval |
| `agentcore run ab-test` | 啟動 A/B Test |
| `agentcore view ab-test` | 查看結果 |
| `agentcore promote ab-test` | Promote Treatment |
| `agentcore stop ab-test` | 停止 Test |
| `agentcore pause ab-test` | 暫停 Test |
| `agentcore resume ab-test` | 恢復 Test |
| `agentcore archive ab-test` | 封存 Test |

---

# 41. 最後檢查清單

- [ ] AgentCore CLI 已更新
- [ ] AgentCore SDK 至少 1.8
- [ ] Transaction Search 已啟用
- [ ] Cognito Token 有效
- [ ] 已產生近期 Trace
- [ ] System Prompt Recommendation 已完成
- [ ] Tool Description Recommendation 已完成
- [ ] Recommendation 已人工審查
- [ ] CustomerSupportAB 已建立
- [ ] A/B Runtime 保留 IAM Auth
- [ ] Config Bundle Hook 可讀取設定
- [ ] Gateway HTTP Runtime Target 已建立
- [ ] Control Bundle 已建立
- [ ] Treatment Bundle 已建立
- [ ] 兩個 Bundle Version ID 已保存
- [ ] ABQualityMonitor 已建立
- [ ] A/B Test 已啟動
- [ ] Gateway URL 使用正確 Target Path
- [ ] 每個 Request 使用不同 Session ID
- [ ] Control 與 Treatment 都有樣本
- [ ] 已查看 P-Value 與 Percent Change
- [ ] 已檢查其他品質與成本指標
- [ ] 已決定 Promote 或 Stop
- [ ] 勝出設定已準備套用 Production
- [ ] A/B 資源已清理

---

# 42. Lab 1～9 完整成果

| Lab | 完成內容 |
|---|---|
| Lab 1 | Agent Prototype 與 Local Tools |
| Lab 2 | Persistent Memory |
| Lab 3 | AgentCore Gateway |
| Lab 4 | JWT、Session、Observability |
| Lab 5 | Continuous Quality Monitoring |
| Lab 6 | Cognito Web Chat Interface |
| Lab 7 | Cedar Policy 與 Tool Governance |
| Lab 8 | Zero-Code Harness Agent |
| Lab 9 | Data-Driven Optimization 與 A/B Testing |

---

# 43. 一句話總結

本 Lab 的核心是：

```text
用真實 Trace 找出 Agent 問題
→ 由 Recommendation 產生改善候選
→ 用 Config Bundle 保存版本
→ 透過 Gateway A/B 分流
→ 用 Online Evaluation 與統計結果驗證
→ Promote 勝出版本
→ 持續重複改善循環
```

AgentCore Optimization 的價值不只是「幫你改 Prompt」，而是：

```text
把 Agent 品質改善從人工猜測，
轉換成可追蹤、可比較、可驗證的工程流程。
```
