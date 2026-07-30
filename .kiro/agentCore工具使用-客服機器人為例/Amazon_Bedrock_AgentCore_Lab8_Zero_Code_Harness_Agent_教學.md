# Amazon Bedrock AgentCore Lab 8：使用 Harness 建立 Zero-Code Agent

## 0. 本 Lab 要完成什麼？

前面的 Lab 已經完成：

- Lab 1：建立 Agent Prototype
- Lab 2：加入 Persistent Memory
- Lab 3：使用 AgentCore Gateway 集中管理 Tool
- Lab 4：加入 Cognito JWT、Session 與 Observability
- Lab 5：加入持續品質評估
- Lab 6：建立 Flask Chat Interface
- Lab 7：使用 Cedar Policy 管理 Tool 權限

本 Lab 會使用 **AgentCore Harness** 建立一個新的：

```text
OrderResearchAgent
```

它不需要：

- `main.py`
- 自訂 Agent Orchestration
- `pyproject.toml`
- 自行管理 Agent Loop
- 自行撰寫 Tool Calling 邏輯

你只需要透過 CLI 宣告：

- 使用哪個模型
- System Prompt
- 可用 Tools
- Gateway
- Credential
- Skills
- Session Storage

AgentCore Harness 會負責執行與協調。

---

# 1. 先理解 AgentCore Harness

AgentCore Harness 是一種受管理的 Agent 執行方式。

傳統 Runtime Agent：

```text
你寫 Python Agent 程式
→ 自己建立 Agent
→ 自己註冊 Tools
→ 自己管理 Session Manager
→ 部署至 Runtime
```

Harness Agent：

```text
你提供宣告式設定
→ AgentCore 建立 Agent
→ AgentCore 管理 Orchestration
→ AgentCore 管理 Session 與 MicroVM
```

---

## 1.1 Runtime Agent 與 Harness Agent 的差異

| 項目 | Runtime Agent | Harness Agent |
|---|---|---|
| Agent 程式 | 自己寫 `main.py` | 不需要 |
| Orchestration | 自己控制 | Harness 管理 |
| Tools | 程式中註冊 | CLI / Config 宣告 |
| Model | 程式設定 | Harness Config |
| Session | 自己整合 | Harness 內建 |
| Shell / Filesystem | 需自行建立 | Harness 內建 |
| 適合情境 | 高度客製流程 | Prompt + Tools 即可完成 |

---

## 1.2 「Zero-Code」的正確理解

本 Lab 的主要 Agent：

```text
OrderResearchAgent
```

可以只靠 CLI 建立，不需要 Application Code。

但後面的 Human-in-the-Loop 範例，由於目前 CLI 無法完整 Resume Inline Function，因此會使用一個 Python 測試腳本。

所以更精確地說：

```text
Harness Agent 本身可以 Zero-Code
但某些整合流程仍可能需要 Client Code
```

---

# 2. 本 Lab 會使用哪些能力？

完成後，你會測試：

1. Zero-Code Harness Agent
2. Existing Secure Gateway
3. OAuth Client Credentials
4. Code Interpreter
5. Shell Access
6. Session Filesystem
7. Per-Invocation Model Override
8. Cedar Policy Enforcement
9. Inline Function
10. Human-in-the-Loop
11. Persistent Session Storage
12. Custom Container
13. Agent Skills

---

# 3. 前置條件

開始前請確認：

- 已完成 Lab 1～4
- 建議已完成 Lab 7
- `my-gateway-secure` 已部署
- Gateway 已設定 Cognito CUSTOM_JWT
- Warranty Tool 可正常使用
- Refund Tool 與 Cedar Policy 已存在
- AgentCore CLI 已安裝
- AWS Credential 尚未過期
- Terminal 位於專案根目錄

---

# 4. Step 1：建立 Harness Agent

在 Windows PowerShell 執行：

```powershell
agentcore add harness `
  --name OrderResearchAgent `
  --model-provider bedrock `
  --model-id us.anthropic.claude-sonnet-4-5-20250929-v1:0 `
  --system-prompt "You are an order research specialist. Help customers investigate order issues, check warranties, and produce detailed analysis reports. Always be thorough and provide structured summaries. Save reports to /tmp/ when asked." `
  --tools agentcore_code_interpreter
```

---

## 4.1 參數說明

| 參數 | 用途 |
|---|---|
| `--name` | Harness Agent 名稱 |
| `--model-provider bedrock` | 使用 Amazon Bedrock |
| `--model-id` | 指定 Foundation Model |
| `--system-prompt` | 定義 Agent 行為 |
| `--tools agentcore_code_interpreter` | 加入 Code Interpreter |

---

## 4.2 建立後的檔案

CLI 會建立：

```text
app/
└── OrderResearchAgent/
    └── harness.json
```

內容概念：

```json
{
  "name": "OrderResearchAgent",
  "model": {
    "provider": "bedrock",
    "modelId": "us.anthropic.claude-sonnet-4-5-20250929-v1:0"
  },
  "systemPrompt": "You are an order research specialist...",
  "tools": [
    {
      "type": "agentcore_code_interpreter",
      "name": "code-interpreter"
    }
  ],
  "skills": [],
  "memory": {
    "mode": "existing",
    "name": "OrderResearchAgentMemory"
  }
}
```

---

# 5. Step 2：為 Harness 準備 Gateway Outbound OAuth

## 5.1 為什麼不能直接連 Gateway？

Secure Gateway 使用：

```text
CUSTOM_JWT
```

Lab 4 的 Runtime Agent 可以把使用者傳入的 Cognito JWT 繼續轉送給 Gateway。

但 Harness Agent 沒有瀏覽器使用者傳入的 JWT 可以直接 Forward。

因此 Harness 必須自己透過：

```text
OAuth Client Credentials
```

取得 Machine-to-Machine Token。

---

## 5.2 如果不設定 Outbound OAuth

`agentcore add tool --type agentcore_gateway` 預設可能使用：

```text
AWS IAM / SigV4
```

但 Gateway 要求的是：

```text
CUSTOM_JWT
```

所以會出現：

```text
401 Unauthorized
Failed to load tool
```

---

# 6. Step 3：取得 AWS 與 Cognito 資訊

## 6.1 取得 Region

```powershell
$REGION = $env:AWS_REGION

if (-not $REGION) {
  $REGION = aws configure get region
}
```

---

## 6.2 取得 AWS Account ID

```powershell
$ACCOUNT_ID = aws sts get-caller-identity `
  --query Account `
  --output text
```

---

## 6.3 取得 Cognito Discovery URL

```powershell
$COGNITO_DISCOVERY_URL = aws ssm get-parameter `
  --name "/app/customersupport/agentcore/cognito_discovery_url" `
  --query "Parameter.Value" `
  --output text
```

---

## 6.4 取得 Machine Client ID

```powershell
$COGNITO_MACHINE_CLIENT_ID = aws ssm get-parameter `
  --name "/app/customersupport/agentcore/client_id" `
  --query "Parameter.Value" `
  --output text
```

---

## 6.5 取得 User Pool ID

```powershell
$COGNITO_POOL_ID = aws ssm get-parameter `
  --name "/app/customersupport/agentcore/pool_id" `
  --query "Parameter.Value" `
  --output text
```

---

## 6.6 取得 OAuth Scope

```powershell
$COGNITO_SCOPE = aws ssm get-parameter `
  --name "/app/customersupport/agentcore/cognito_auth_scope" `
  --query "Parameter.Value" `
  --output text
```

---

## 6.7 取得 Machine Client Secret

```powershell
$COGNITO_MACHINE_SECRET = aws cognito-idp describe-user-pool-client `
  --user-pool-id $COGNITO_POOL_ID `
  --client-id $COGNITO_MACHINE_CLIENT_ID `
  --query "UserPoolClient.ClientSecret" `
  --output text
```

> Client Secret 是敏感資料，不要提交至 Git 或貼到公開聊天室。

---

# 7. Step 4：組合 Credential Provider ARN

Credential Provider ARN 格式固定：

```powershell
$PROVIDER_ARN = "arn:aws:bedrock-agentcore:${REGION}:${ACCOUNT_ID}:token-vault/default/oauth2credentialprovider/gateway-egress-oauth"
```

確認：

```powershell
Write-Host "Provider ARN: $PROVIDER_ARN"
```

這個 Provider 可以在真正建立前先被 Tool Config 引用，因為 ARN 格式是可預測的。

---

# 8. Step 5：取得 Secure Gateway ARN

取得 Gateway ID：

```powershell
$GATEWAY_ID = aws bedrock-agentcore-control list-gateways `
  --query "items[?contains(name, 'my-gateway-secure')].gatewayId | [0]" `
  --output text
```

取得 Gateway ARN：

```powershell
$GATEWAY_ARN = aws bedrock-agentcore-control get-gateway `
  --gateway-identifier $GATEWAY_ID `
  --query "gatewayArn" `
  --output text
```

確認：

```powershell
Write-Host "Gateway ARN: $GATEWAY_ARN"
```

---

# 9. Step 6：建立 OAuth Credential Provider

執行：

```powershell
agentcore add credential `
  --type oauth `
  --name gateway-egress-oauth `
  --discovery-url $COGNITO_DISCOVERY_URL `
  --client-id $COGNITO_MACHINE_CLIENT_ID `
  --client-secret $COGNITO_MACHINE_SECRET `
  --scopes $COGNITO_SCOPE
```

這個 Credential Provider 會讓 Harness：

```text
使用 Machine Client
→ 取得 Cognito Access Token
→ 帶 Token 呼叫 Secure Gateway
```

---

# 10. Step 7：把 Gateway Tool 加入 Harness

```powershell
agentcore add tool `
  --harness OrderResearchAgent `
  --type agentcore_gateway `
  --name my-gateway-secure `
  --gateway-arn $GATEWAY_ARN `
  --outbound-auth oauth `
  --provider-arn $PROVIDER_ARN `
  --scopes $COGNITO_SCOPE `
  --grant-type CLIENT_CREDENTIALS
```

---

## 10.1 為什麼使用 Gateway ARN？

工作坊指出：

```text
--gateway <name>
```

可能無法從 Local Deployed State 正確解析。

因此直接使用：

```text
--gateway-arn
```

較穩定。

---

## 10.2 更新後的 `harness.json`

概念：

```json
{
  "type": "agentcore_gateway",
  "name": "my-gateway-secure",
  "config": {
    "agentCoreGateway": {
      "gatewayArn": "<GATEWAY_ARN>",
      "outboundAuth": {
        "oauth": {
          "providerArn": "<PROVIDER_ARN>",
          "scopes": [
            "<COGNITO_SCOPE>"
          ],
          "grantType": "CLIENT_CREDENTIALS"
        }
      }
    }
  }
}
```

---

# 11. Step 8：部署 Harness

執行：

```powershell
agentcore deploy -y -v
```

這次部署會處理：

- Harness Agent
- Code Interpreter
- OAuth Credential Provider
- Gateway Tool
- Harness Runtime Environment
- 相關 IAM 權限

---

# 12. Step 9：測試 Harness Agent

建立 Session：

```powershell
$SESSION = [guid]::NewGuid().ToString()
```

呼叫：

```powershell
agentcore invoke `
  --harness OrderResearchAgent `
  --session-id $SESSION `
  --actor-id "analyst-1" `
  "Check the warranty for PROD-001 and PROD-003. Save a comparison report to /tmp/warranty_report.md summarizing which products are still covered."
```

---

## 12.1 預期流程

```text
Harness Agent
    ↓
透過 Gateway 呼叫 check_warranty(PROD-001)
    ↓
透過 Gateway 呼叫 check_warranty(PROD-003)
    ↓
整理比較結果
    ↓
使用 Code Interpreter / Shell
    ↓
寫入 /tmp/warranty_report.md
```

---

# 13. Step 10：使用 Shell Access

Harness 提供：

```text
Linux MicroVM
```

可以透過 `--exec` 執行命令。

查看報告：

```powershell
agentcore invoke `
  --exec `
  --harness OrderResearchAgent `
  --session-id $SESSION `
  "cat /tmp/warranty_report.md"
```

查看環境：

```powershell
agentcore invoke `
  --exec `
  --harness OrderResearchAgent `
  --session-id $SESSION `
  "python3 --version && ls -la /tmp/"
```

---

## 13.1 `--exec` 的重要限制

目前 Preview CLI 中：

```text
命令確實在 MicroVM 中執行
但結果仍可能經過 Agent 回覆包裝
```

所以它不是完全：

```text
Raw Shell Passthrough
```

你可能會看到 Agent 對 Shell Output 做簡短摘要。

---

## 13.2 何時適合使用 `--exec`？

適合執行決定性的任務：

```bash
wc -l /tmp/report.csv
cat /tmp/report.md
ls -la /tmp/
python3 script.py
```

與其叫 LLM 猜 CSV 有幾列，不如直接用 `wc -l`。讓模型算行數，有時像請詩人做稅務申報。

---

# 14. Step 11：測試 Session Filesystem Persistence

同一個 Harness Session 中，檔案會持續存在。

請 Agent 修改原本報告：

```powershell
agentcore invoke `
  --harness OrderResearchAgent `
  --session-id $SESSION `
  --actor-id "analyst-1" `
  "Read the report at /tmp/warranty_report.md and add a recommendation section for each expired product."
```

再次查看：

```powershell
agentcore invoke `
  --exec `
  --harness OrderResearchAgent `
  --session-id $SESSION `
  "cat /tmp/warranty_report.md"
```

---

## 14.1 Persistence 範圍

```text
相同 Session ID
→ 同一 Session Filesystem
→ 檔案持續存在
```

新的 Session ID：

```text
可能是新的隔離環境
→ 原本 /tmp 檔案不一定存在
```

---

# 15. Step 12：每次 Invocation 覆寫模型

可以不重新部署，直接指定另一個 Model：

```powershell
agentcore invoke `
  --harness OrderResearchAgent `
  --model-id us.amazon.nova-2-lite-v1:0 `
  --session-id $SESSION `
  --actor-id "analyst-1" `
  "Summarize the warranty report in exactly 3 bullet points."
```

---

## 15.1 適用情境

- 測試低成本模型
- 複雜任務改用高能力模型
- A/B Test
- 比較不同模型品質
- 不希望每次更換模型都重新部署

Session 與 Filesystem 仍維持原本狀態。

---

# 16. Step 13：驗證 Cedar Policy 仍然生效

Harness 使用的是同一個：

```text
my-gateway-secure
```

所以自動繼承 Lab 7 的 Cedar Policies。

建立新 Session：

```powershell
$POLICY_SESSION = [guid]::NewGuid().ToString()
```

測試大額退款：

```powershell
agentcore invoke `
  --harness OrderResearchAgent `
  --session-id $POLICY_SESSION `
  --actor-id "analyst-1" `
  "Process a refund of $500 for order ORD-12345 because the customer is unhappy."
```

預期：

```text
Refund Policy DENY
```

原因：

- Amount 大於或等於 100
- Reason 不包含 `defective`
- Gateway Policy 與 Agent 類型無關

---

## 16.1 關鍵觀念

Cedar Policy 保護的是：

```text
Gateway
```

不是某一個 Agent。

因此：

```text
Runtime Agent
Harness Agent
其他 MCP-Compatible Agent
```

只要呼叫相同 Gateway，就必須遵守相同規則。

---

# 17. Step 14：建立 Inline Function

Inline Function 適合：

- Human Approval
- 外部 API
- Queue
- Slack Workflow
- 不能在 Harness VM 內完成的邏輯

新增 Approval Tool：

```powershell
agentcore add tool `
  --harness OrderResearchAgent `
  --type inline_function `
  --name approve_exception `
  --description "Request manager approval for a refund that exceeds the automated limit. Returns approved or denied with approver name." `
  --input-schema '{"type":"object","properties":{"order_id":{"type":"string"},"amount":{"type":"number"},"reason":{"type":"string"}},"required":["order_id","amount","reason"]}'
```

部署：

```powershell
agentcore deploy -y -v
```

---

# 18. Inline Function 如何運作？

流程：

```text
1. Agent 決定呼叫 approve_exception
2. Harness 暫停
3. 回傳 stopReason = tool_use
4. Client 收到 Tool Name、Input、toolUseId
5. Client 執行外部流程
6. Client 回傳 toolResult
7. Harness 恢復 Agent 推理
```

---

# 19. CLI 限制

目前：

```text
agentcore invoke --harness
```

尚不能正確 Resume Inline Function 的 `toolResult`。

CLI 可能把 Resume Input 當成新的 User Message，而不是 Tool Result。

因此完整 HITL Demo 需要：

```text
Python + boto3 invoke_harness
```

這是本 Lab 中唯一需要程式碼的主要步驟。

---

# 20. Step 15：建立 HITL 測試腳本

建立：

```text
app/OrderResearchAgent/test_hitl.py
```

```python
"""
Human-in-the-Loop test for AgentCore Harness inline functions.
"""

import argparse
import json
import os
import uuid

import boto3


DEFAULT_PROMPT = (
    "A customer needs a $200 refund for order ORD-55555 "
    "because they received a damaged product. "
    "Try to process it, and if you can't, "
    "escalate for manager approval."
)


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Test HITL inline functions "
            "with AgentCore Harness"
        )
    )

    parser.add_argument(
        "--harness-arn",
        default=os.environ.get("HARNESS_ARN"),
        help=(
            "Harness ARN. Defaults to HARNESS_ARN "
            "environment variable."
        ),
    )

    parser.add_argument(
        "--prompt",
        default=DEFAULT_PROMPT,
        help="Prompt to send to the agent.",
    )

    return parser.parse_args()


def parse_stream(response):
    """Parse streaming response and return tool call information."""

    tool_use_id = None
    tool_name = None
    tool_input_chunks = ""
    stop_reason = None
    current_block_is_tool = False

    for event in response["stream"]:
        if "contentBlockStart" in event:
            start = event["contentBlockStart"].get(
                "start",
                {},
            )

            if "toolUse" in start:
                tool_use_id = start["toolUse"][
                    "toolUseId"
                ]
                tool_name = start["toolUse"].get(
                    "name"
                )
                tool_input_chunks = ""
                current_block_is_tool = True
            else:
                current_block_is_tool = False

        elif "contentBlockDelta" in event:
            delta = event["contentBlockDelta"].get(
                "delta",
                {},
            )

            if "text" in delta:
                print(
                    delta["text"],
                    end="",
                    flush=True,
                )

            elif (
                "toolUse" in delta
                and current_block_is_tool
            ):
                tool_input_chunks += delta[
                    "toolUse"
                ].get(
                    "input",
                    "",
                )

        elif "contentBlockStop" in event:
            current_block_is_tool = False

        elif "messageStop" in event:
            stop_reason = event["messageStop"].get(
                "stopReason"
            )

    print()

    tool_input = None

    if tool_input_chunks:
        try:
            tool_input = json.loads(
                tool_input_chunks
            )

        except json.JSONDecodeError:
            decoder = json.JSONDecoder()

            try:
                tool_input, _ = decoder.raw_decode(
                    tool_input_chunks
                )
            except json.JSONDecodeError:
                tool_input = {}

    return {
        "tool_use_id": tool_use_id,
        "tool_name": tool_name,
        "tool_input": tool_input,
        "stop_reason": stop_reason,
    }


def main():
    args = parse_args()
    harness_arn = args.harness_arn

    if not harness_arn:
        print(
            "Error: HARNESS_ARN not set. "
            "Export it or pass --harness-arn."
        )
        raise SystemExit(1)

    client = boto3.client(
        "bedrock-agentcore"
    )

    session_id = str(
        uuid.uuid4()
    )

    response = client.invoke_harness(
        harnessArn=harness_arn,
        runtimeSessionId=session_id,
        messages=[
            {
                "role": "user",
                "content": [
                    {
                        "text": args.prompt
                    }
                ],
            }
        ],
    )

    result = parse_stream(response)

    if (
        result["stop_reason"] == "tool_use"
        and result["tool_name"]
        == "approve_exception"
    ):
        print(
            f"\nAgent called: "
            f"{result['tool_name']}"
        )

        print(
            "Input: "
            + json.dumps(
                result["tool_input"],
                indent=2,
            )
        )

        approval = input(
            "\nApprove this refund? "
            "(yes/no): "
        ).strip().lower()

        if approval in ("yes", "y"):
            tool_result = json.dumps(
                {
                    "approved": True,
                    "approver": "manager-jane",
                }
            )
        else:
            tool_result = json.dumps(
                {
                    "approved": False,
                    "reason": "Manager denied",
                }
            )

        tool_input_value = (
            result["tool_input"]
            if isinstance(
                result["tool_input"],
                dict,
            )
            else {}
        )

        response = client.invoke_harness(
            harnessArn=harness_arn,
            runtimeSessionId=session_id,
            messages=[
                {
                    "role": "assistant",
                    "content": [
                        {
                            "toolUse": {
                                "toolUseId": (
                                    result[
                                        "tool_use_id"
                                    ]
                                ),
                                "name": (
                                    result[
                                        "tool_name"
                                    ]
                                ),
                                "input": (
                                    tool_input_value
                                ),
                            }
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "toolResult": {
                                "toolUseId": (
                                    result[
                                        "tool_use_id"
                                    ]
                                ),
                                "content": [
                                    {
                                        "text": (
                                            tool_result
                                        )
                                    }
                                ],
                                "status": "success",
                            }
                        }
                    ],
                },
            ],
        )

        parse_stream(response)

    else:
        print(
            "\nAgent completed. "
            f"Stop reason: "
            f"{result['stop_reason']}"
        )


if __name__ == "__main__":
    main()
```

---

# 21. Step 16：取得 Harness ARN

```powershell
$env:HARNESS_ARN = aws bedrock-agentcore-control list-harnesses `
  --query "harnesses[?contains(harnessName, 'OrderResearchAgent')].arn | [0]" `
  --output text
```

確認：

```powershell
Write-Host "HARNESS_ARN=$env:HARNESS_ARN"
```

---

# 22. Step 17：執行 HITL 測試

```powershell
python app\OrderResearchAgent\test_hitl.py
```

預期流程：

```text
Agent 嘗試退款 $200
    ↓
Gateway Cedar Policy 阻擋
    ↓
Agent 改呼叫 approve_exception
    ↓
Harness 暫停並回傳 tool_use
    ↓
Python Script 詢問人工是否核准
    ↓
人工輸入 yes / no
    ↓
Script 回傳 toolResult
    ↓
Agent 繼續完成回答
```

---

# 23. Resume Inline Function 的關鍵格式

Resume 時必須同時傳送兩則 Message：

```python
messages=[
    {
        "role": "assistant",
        "content": [
            {
                "toolUse": {
                    "toolUseId": "...",
                    "name": "...",
                    "input": {}
                }
            }
        ],
    },
    {
        "role": "user",
        "content": [
            {
                "toolResult": {
                    "toolUseId": "...",
                    "content": [
                        {
                            "text": "..."
                        }
                    ],
                    "status": "success",
                }
            }
        ],
    },
]
```

第一則：

```text
重新帶回 Agent 原本的 Tool Use
```

第二則：

```text
提供外部系統或人工回傳的 Tool Result
```

兩者缺一不可。

---

# 24. Production HITL Pattern

正式環境的人工作業可以是：

- Slack Approval
- Microsoft Teams Approval
- SQS Queue
- Internal Approval Dashboard
- Supervisor Agent
- Ticketing System
- Web Modal
- Email Approval

流程概念：

```text
Agent Request
→ Inline Function
→ Pause
→ 外部審批
→ Tool Result
→ Resume
```

---

# 25. Bonus A：Persistent Session Storage

預設 `/tmp` 檔案只存在於 Session 生命週期。

如果需要跨 Stop / Resume 保留檔案，可以建立新的 Harness：

```powershell
agentcore add harness `
  --name PersistentReportAgent `
  --model-provider bedrock `
  --model-id us.anthropic.claude-sonnet-4-5-20250929-v1:0 `
  --system-prompt "You are a report writer. Save all reports to /mnt/reports/ for persistent storage." `
  --tools agentcore_code_interpreter `
  --session-storage /mnt/reports/
```

寫入：

```text
/mnt/reports/
```

的檔案會針對相同 Session ID 保留。

---

## 25.1 為什麼要建立新的 Harness？

工作坊指出 Harness 目前不能用相同名稱原地更新。

重新執行：

```text
agentcore add harness --name OrderResearchAgent
```

可能會發生 Duplicate Error。

因此使用新名稱：

```text
PersistentReportAgent
```

---

# 26. Bonus B：Custom Container

可以讓 Harness 使用自訂 Container Image：

```powershell
agentcore add harness `
  --name ContainerAgent `
  --model-provider bedrock `
  --model-id us.anthropic.claude-sonnet-4-5-20250929-v1:0 `
  --system-prompt "You are a development assistant with access to git and node." `
  --container public.ecr.aws/docker/library/node:slim
```

---

## 26.1 Container 提供什麼？

Container 提供：

- 已安裝軟體
- CLI Tools
- Libraries
- Filesystem
- Environment Variables

但不會取代 Harness Orchestration。

Harness 仍然使用它自己的：

```text
Managed Strands Agent Loop
```

Container 的：

```text
ENTRYPOINT
CMD
```

會被 Harness 覆寫。

可以理解成：

```text
你提供一台預先裝好軟體的電腦
但 Agent 的大腦與執行流程仍由 Harness 管理
```

---

## 26.2 適用情境

- Git
- Node.js
- Terraform
- Domain-Specific CLI
- 大型 Python Library
- 編譯工具
- 資料處理套件

---

# 27. Bonus C：Agent Skills

可以透過 Markdown-Based Skills 擴充 Harness Agent。

例如加入 XLSX Skill：

```powershell
agentcore add skill `
  --harness OrderResearchAgent `
  --git https://github.com/anthropics/skills `
  --git-path skills/xlsx
```

部署：

```powershell
agentcore deploy -y -v
```

更新後的 `harness.json`：

```json
{
  "skills": [
    {
      "gitUrl": "https://github.com/anthropics/skills",
      "path": "skills/xlsx"
    }
  ]
}
```

---

## 27.1 測試 Skill

```powershell
agentcore invoke `
  --harness OrderResearchAgent `
  --session-id $SESSION `
  --actor-id "analyst-1" `
  "Create an Excel (.xlsx) report summarizing the warranty status of PROD-001 and PROD-003, then tell me where you saved it."
```

---

## 27.2 Per-Invocation Skill

也可以只在單次 Invocation 使用：

```text
--skills .agents/skills/xlsx
```

多個 Skill 使用逗號分隔。

---

# 28. 完成後的整體架構

```text
Runtime CustomerSupport Agent
└── Secure Gateway
    ├── Warranty Tool
    └── Refund Tool
        └── Cedar Policies

OrderResearchAgent Harness
├── Bedrock Model
├── Code Interpreter
├── Linux MicroVM
├── Session Filesystem
├── Gateway OAuth Credential
├── Secure Gateway
├── Inline Functions
├── Model Override
└── Skills

兩種 Agent
→ 共用相同 Gateway
→ 共用相同 Cedar Governance
```

---

# 29. Harness 的重要優勢

## 29.1 不用寫 Orchestration Code

不必自己建立：

- Agent Object
- Tool Loop
- Streaming Logic
- Runtime Entrypoint
- Session Lifecycle

---

## 29.2 內建執行環境

提供：

- Linux MicroVM
- Shell
- Filesystem
- Code Interpreter
- Session Isolation

---

## 29.3 可重用既有企業 Tool

Harness 可以連接：

- AgentCore Gateway
- MCP Server
- Inline Function
- Built-in Tool
- Skills

---

## 29.4 Governance 自動繼承

Policy 位於 Gateway，因此：

```text
不論哪一種 Agent
都不能繞過 Gateway Policy
```

---

# 30. 常見錯誤排查

## 30.1 Gateway 回傳 401

可能原因：

- 沒有設定 Outbound OAuth
- 使用 AWS IAM 對 CUSTOM_JWT Gateway
- Provider ARN 錯誤
- Client ID / Secret 錯誤
- Scope 錯誤
- Credential Provider 尚未部署

---

## 30.2 Gateway Name 找不到

使用：

```text
--gateway-arn
```

不要依賴：

```text
--gateway <name>
```

---

## 30.3 Harness 看不到 Warranty Tool

檢查：

- Gateway Tool 是否加入 Harness
- Gateway ARN 是否正確
- OAuth Credential 是否正確
- Gateway Target 是否存在
- Cedar Policy 是否允許
- `agentcore deploy` 是否成功

---

## 30.4 Refund 被拒絕

這可能是正常行為。

檢查：

- Amount 是否大於或等於 100
- Reason 是否包含 `defective`
- Lab 7 Cedar Policy

---

## 30.5 `/tmp` 報告消失

可能原因：

- 使用了新的 Session ID
- Session 已終止
- 檔案只存在 Session Filesystem
- 沒有使用 `--session-storage`

---

## 30.6 `--exec` 回傳 Agent 摘要

這是 Preview CLI 行為。

命令仍有執行，但 Output 可能經過 Agent 回覆包裝。

---

## 30.7 Inline Function 無法從 CLI Resume

這是目前 CLI 限制。

使用：

```text
boto3 invoke_harness
```

並正確回傳：

- Assistant `toolUse`
- User `toolResult`

---

## 30.8 Harness 重複名稱錯誤

Harness 可能不能原地更新。

使用新的名稱，例如：

```text
PersistentReportAgent
ContainerAgent
```

---

## 30.9 Model Override 失敗

檢查：

- Model ID 是否正確
- Region 是否支援
- AWS 帳號是否有模型存取權
- IAM 是否允許呼叫模型

---

# 31. 安全與實務注意事項

## 31.1 Machine Credential 必須安全保存

不要將：

```text
COGNITO_MACHINE_SECRET
```

寫入：

- Git
- `harness.json`
- README
- Log
- Chat

---

## 31.2 Harness Shell 仍需權限控制

Harness 可以執行 Shell 與讀寫 Filesystem。

正式環境應限制：

- Network Access
- IAM Role
- Available Tools
- Container Packages
- Sensitive Files
- Session Lifetime

---

## 31.3 Inline Function 不等於自動繞過 Policy

Human Approval Tool 只是建立 Exception Workflow。

真正的大額退款仍應：

- 由另一個受控 Tool 執行
- 記錄 Approver
- 保留 Audit Trail
- 驗證 Order Ownership
- 使用 Idempotency Key

不要因為 Manager 按了 Yes，就讓 Agent 直接「憑感覺入帳」。

---

## 31.4 Harness 仍可能產生成本

雖然 Harness 本身可採受管理方式，但仍可能產生：

- Model Token Cost
- Code Interpreter Cost
- Runtime / Compute Cost
- Gateway Cost
- Memory Cost
- Evaluation Cost
- Storage Cost

---

# 32. 完整操作順序

```text
Step 1
建立 OrderResearchAgent Harness
    ↓
Step 2
取得 Region、Account、Cognito 資訊
    ↓
Step 3
建立 OAuth Credential Provider
    ↓
Step 4
取得 Secure Gateway ARN
    ↓
Step 5
將 Gateway 加入 Harness
    ↓
Step 6
部署 Harness
    ↓
Step 7
查 Warranty 並建立 Markdown Report
    ↓
Step 8
使用 --exec 查看檔案
    ↓
Step 9
測試 Session Filesystem
    ↓
Step 10
Override Model
    ↓
Step 11
測試 Cedar Policy
    ↓
Step 12
加入 Inline Function
    ↓
Step 13
建立 HITL Python Script
    ↓
Step 14
人工 Approve / Deny
    ↓
Bonus
Session Storage / Container / Skills
```

---

# 33. 指令速查表

| 指令 | 用途 |
|---|---|
| `agentcore add harness` | 建立 Harness Agent |
| `agentcore add credential` | 建立 OAuth Credential Provider |
| `agentcore add tool` | 加入 Gateway 或 Inline Function |
| `agentcore deploy -y -v` | 部署 Harness |
| `agentcore invoke --harness` | 呼叫 Harness Agent |
| `agentcore invoke --exec` | 在 Harness MicroVM 執行命令 |
| `--model-id` | 單次 Invocation 覆寫模型 |
| `--session-storage` | 設定 Persistent Session Storage |
| `--container` | 使用 Custom Container |
| `agentcore add skill` | 加入 Agent Skill |

---

# 34. 最後檢查清單

- [ ] Lab 1～4 已完成
- [ ] Secure Gateway 已部署
- [ ] OrderResearchAgent Harness 已建立
- [ ] Code Interpreter 已加入
- [ ] Region 與 Account ID 已取得
- [ ] Cognito Machine Client 已取得
- [ ] Cognito Scope 已取得
- [ ] Machine Client Secret 已取得
- [ ] OAuth Credential Provider 已建立
- [ ] Secure Gateway ARN 已取得
- [ ] Gateway Tool 已加入 Harness
- [ ] Harness 已部署
- [ ] Warranty Report 已成功建立
- [ ] `/tmp/warranty_report.md` 可讀取
- [ ] 同一 Session 可持續修改檔案
- [ ] Model Override 可執行
- [ ] 大額退款被 Cedar Policy 拒絕
- [ ] Inline Function 已加入
- [ ] HITL Script 可捕捉 Tool Use
- [ ] Human Approval 後 Agent 可 Resume
- [ ] 已理解 Zero-Code 與 Client Code 的差異
- [ ] 已理解 Session Storage、Container 與 Skills

---

# 35. Lab 1～8 完整成果

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

---

# 36. 一句話總結

本 Lab 的核心流程是：

```text
用 CLI 宣告 Model、Prompt 與 Tools
→ 建立 Zero-Code Harness Agent
→ 使用 OAuth 連接 Secure Gateway
→ 共用既有 Cedar Policies
→ 使用 Shell 與 Session Filesystem
→ 單次切換 Model
→ 用 Inline Function 建立 Human-in-the-Loop
```

AgentCore Harness 的價值在於：

```text
當需求只需要 Model、Prompt 與 Tools 時，
不必為了「像 Agent」而先寫一整套 Agent Framework 程式。
```
