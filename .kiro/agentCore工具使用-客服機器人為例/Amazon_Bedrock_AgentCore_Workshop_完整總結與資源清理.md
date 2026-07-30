# Amazon Bedrock AgentCore Workshop：完整總結與資源清理

## 0. 這個工作坊完成了什麼？

這個工作坊從零開始，逐步建立一套接近正式環境的 Customer Support Agent。

完整演進路線：

```text
建立 Agent Prototype
→ 加入 Memory
→ 集中管理 Tools
→ 部署與安全驗證
→ Observability
→ 持續品質評估
→ Web Chat Interface
→ Cedar Policy Governance
→ Zero-Code Harness
→ Recommendation 與 A/B Testing
```

最後完成的系統不只是「一個會聊天的 Agent」，而是一套包含：

- Agent Runtime
- Persistent Memory
- MCP Gateway
- Cognito Authentication
- Observability
- Evaluation
- Web Interface
- Policy Governance
- Zero-Code Agent
- Optimization Loop

的完整 Agent 平台實作。

---

# 1. Lab 1～9 成果總覽

| Lab | 完成內容 | 主要 AgentCore 能力 |
|---|---|---|
| Lab 1 | 建立專案、加入 Local Tools、整合 Exa AI MCP、使用 `agentcore dev` 本機測試 | AgentCore CLI、Runtime Local Development |
| Lab 2 | 加入跨 Session 的事實與摘要記憶，首次部署至 AWS | AgentCore Memory、Runtime |
| Lab 3 | 將既有 Lambda 轉換成 MCP Tool，供多個 Agent 共用 | AgentCore Gateway |
| Lab 4 | 使用 Cognito JWT 保護 Runtime 與 Gateway，查看 Session、Trace、Log、Metrics | Identity、Observability |
| Lab 5 | 建立持續品質監控，評估 Goal、Correctness、Tool Selection | AgentCore Evaluations |
| Lab 6 | 建立 Flask Chat UI，使用 Cognito Hosted UI 登入 | Runtime、Identity、Gateway、Memory 整合 |
| Lab 7 | 使用 Cedar Policy 控制退款金額與 Tool 權限 | AgentCore Policy |
| Lab 8 | 使用 CLI 建立 Zero-Code Harness Agent，測試 Shell、Filesystem、Model Override、HITL | AgentCore Harness |
| Lab 9 | 根據 Trace 產生改善建議，透過 Config Bundle 與 A/B Testing 驗證 | AgentCore Optimization |

---

# 2. 完成後的整體架構

```text
使用者 Browser
    │
    │ Cognito Login / JWT
    ▼
Flask Chat Backend
    │
    ▼
AgentCore Runtime
    ├── Session Management
    ├── AgentCore Memory
    │   ├── SEMANTIC
    │   └── SUMMARIZATION
    ├── Local Tools
    │   ├── get_product_info
    │   └── get_return_policy
    ├── Exa AI MCP
    └── Secure AgentCore Gateway
            │
            ├── Warranty Lambda
            ├── Refund Lambda
            └── Cedar Policy Engine
                    ├── Warranty Permit
                    └── Refund Limit

CloudWatch
    ├── Traces
    ├── Logs
    ├── Metrics
    └── GenAI Observability
            │
            ▼
AgentCore Evaluations
    ├── GoalSuccessRate
    ├── Correctness
    └── ToolSelectionAccuracy
            │
            ▼
AgentCore Optimization
    ├── Prompt Recommendation
    ├── Tool Description Recommendation
    ├── Config Bundles
    └── A/B Testing
```

另外還建立：

```text
OrderResearchAgent Harness
├── Zero-Code Configuration
├── Code Interpreter
├── Linux MicroVM
├── Session Filesystem
├── Secure Gateway
├── Cedar Policies
├── Inline Functions
└── Human-in-the-Loop
```

---

# 3. 核心觀念一：AgentCore CLI 抽象基礎設施複雜度

工作坊中主要使用：

```powershell
agentcore create
agentcore add
agentcore validate
agentcore deploy
agentcore status
agentcore invoke
agentcore remove
```

你沒有手動完成：

- 撰寫 Dockerfile
- 建立 ECR Repository
- 手動建立 Runtime IAM Role
- 手動封裝 Python Dependencies
- 自行上傳 Deployment Package
- 手動建立大部分 CloudFormation Resource
- 手動注入 Memory ID 與 Gateway URL

執行：

```powershell
agentcore deploy
```

CLI 會協助處理：

```text
讀取本機設定
→ 驗證 Project
→ 封裝程式與 Dependencies
→ 上傳 Deployment Artifact
→ 建立或更新 CloudFormation
→ 建立 IAM Role
→ 建立 Runtime、Memory、Gateway 等資源
→ 注入 Environment Variables
→ 保存 Deployment State
```

---

# 4. 核心觀念二：CLI 不是雲端平台本身

```text
AgentCore
＝ AWS 提供的 Agent Platform Services

AgentCore CLI
＝ 從本機操作這些服務的命令列工具
```

並不是每個 CLI 指令都直接操作雲端：

| 指令 | 主要用途 |
|---|---|
| `agentcore create` | 建立本機專案骨架 |
| `agentcore dev` | 啟動本機開發環境 |
| `agentcore add ...` | 更新本機宣告式設定 |
| `agentcore validate` | 驗證設定 |
| `agentcore deploy` | 真正建立或更新 AWS 資源 |
| `agentcore status` | 查詢 AWS 資源 |
| `agentcore invoke` | 呼叫已部署 Agent |
| `agentcore remove ...` | 標記要移除的資源 |
| `agentcore deploy` | 實際執行移除 |

---

# 5. 核心觀念三：AgentCore 不限制特定 Framework 或 Model

本工作坊使用：

```text
Strands Agents
＋
Claude on Amazon Bedrock
```

但 AgentCore 的設計並不只綁定 Strands。

可以搭配：

- Strands Agents
- LangGraph
- CrewAI
- OpenAI Agents SDK
- Google ADK
- 其他 Agent Framework
- 不同 Foundation Model Provider

正確理解：

```text
Agent Framework
負責 Agent 邏輯與 Orchestration

Foundation Model
負責推理與生成

AgentCore
負責執行、部署、記憶、工具、安全、觀測與治理
```

---

# 6. 核心觀念四：Memory 讓 Prototype 變成可持續使用的產品

沒有 Memory：

```text
每次對話重新開始
→ 使用者重複提供姓名、偏好與歷史資訊
```

加入 AgentCore Memory：

```text
SEMANTIC
→ 保存姓名、偏好、購買紀錄等事實

SUMMARIZATION
→ 保存壓縮後的對話摘要
```

Session 與 Memory 的差異：

| 概念 | 作用 |
|---|---|
| Session Context | 保存同一段對話中的短期歷史 |
| Semantic Memory | 跨 Session 保存使用者事實 |
| Summarization | 保存某個 Session 的對話摘要 |

---

# 7. 核心觀念五：Gateway 將既有企業服務轉成 Agent Tools

企業通常已經擁有：

- Lambda
- REST API
- API Gateway
- Internal Service
- OpenAPI Service
- MCP Server
- Smithy Service

但這些服務未必有 Agent 能理解的：

- Tool Name
- Natural Language Description
- Input Schema
- Discovery Protocol

AgentCore Gateway 透過：

```text
既有 Service
＋
Tool Schema
→ MCP-Compatible Tool
```

讓 Agent 可以自動發現與呼叫。

原始 Lambda 不需要為 Agent 重寫。

---

# 8. 核心觀念六：安全是設定與 Token Flow，不只是登入頁

Lab 4 建立：

```text
Client
→ Cognito JWT
→ AgentCore Runtime
→ JWT Forwarding
→ Secure Gateway
```

Runtime 與 Gateway 是兩個不同 Endpoint，因此必須分別保護。

只保護 Runtime：

```text
使用者不能直接呼叫 Runtime
但可能仍可直接呼叫 Gateway
```

完整安全流程：

```text
Cognito 驗證使用者
→ Runtime 驗證 JWT
→ Agent 取得 User Identity
→ MCP Client 轉送 JWT
→ Gateway 再次驗證 JWT
→ 才能呼叫 Lambda Tool
```

---

# 9. 核心觀念七：Governance 應位於 Agent 外部

只在 System Prompt 寫：

```text
請不要退款超過 100 美元
```

不是可靠的安全規則。

模型可能：

- 誤解
- 遺漏
- 被 Prompt Injection 影響
- 選錯 Tool
- 產生不確定行為

AgentCore Policy 使用 Cedar，在 Gateway 邊界執行：

```cedar
context.input.amount < 100
```

因此：

```text
Agent 想執行
≠ Gateway 一定允許
```

Policy 的優點：

- 決定性
- Agent 無法自行繞過
- 不必修改 Agent Code
- 不必修改 Lambda Code
- 可記錄 Audit Trail
- 可集中管理所有 Gateway Tools

---

# 10. 核心觀念八：Observability 與 Evaluation 是兩個不同層次

## Observability

回答：

```text
Agent 發生了什麼？
```

包含：

- Prompt
- Tool Selection
- Tool Input
- Tool Output
- Memory Retrieval
- Gateway Invocation
- Latency
- Error
- Token Usage

---

## Evaluation

回答：

```text
Agent 做得好不好？
```

包含：

- Goal Success
- Correctness
- Tool Selection Accuracy

完整流程：

```text
Invocation
→ Trace
→ Evaluation
→ Score
→ Low-Score Session
→ Root Cause Analysis
```

---

# 11. 核心觀念九：Optimization 將監控資料變成改善循環

只知道：

```text
GoalSuccessRate = 72%
```

無法直接告訴你如何提升到 90%。

AgentCore Optimization 使用：

```text
Production Traces
＋
Evaluation Results
```

產生：

- System Prompt Recommendation
- Tool Description Recommendation

接著透過：

- Config Bundle
- Gateway A/B Testing
- Online Evaluation
- Statistical Significance

判斷 Treatment 是否真的優於 Control。

完整循環：

```text
Observe
→ Evaluate
→ Recommend
→ Experiment
→ Promote
→ Repeat
```

---

# 12. 核心觀念十：Harness 適合不需要自訂 Orchestration 的 Agent

Runtime Agent 適合：

- 複雜流程
- 自訂程式
- 特殊 Session Logic
- 自訂 Framework
- 特殊 Streaming
- 深度 Backend Integration

Harness Agent 適合：

```text
Model
＋
System Prompt
＋
Tools
```

就足以完成的需求。

Harness 可以提供：

- Managed Agent Loop
- Shell
- Filesystem
- Code Interpreter
- Gateway Tools
- Inline Functions
- Model Override
- Skills
- Session Storage

---

# 13. 工作坊最終形成的 Agent 生命週期

```text
1. Create
建立 Agent Project

2. Develop
Local Tools、Prompt、MCP

3. Test
agentcore dev、Inspector

4. Deploy
AgentCore Runtime

5. Remember
AgentCore Memory

6. Connect
AgentCore Gateway

7. Secure
Cognito JWT、Identity

8. Observe
CloudWatch Traces、Logs、Metrics

9. Evaluate
Goal、Correctness、Tool Selection

10. Govern
Cedar Policy

11. Interface
Flask Web Chat

12. Optimize
Recommendation、A/B Testing

13. Operate
Monitor、Promote、Rollback、Cleanup
```

---

# 14. 清理前的重要確認

資源清理會真的刪除 AWS 資源。

執行前先確認：

## 14.1 確認 AWS 身分

```powershell
aws sts get-caller-identity
```

確認：

- Account ID
- ARN
- Assumed Role
- 是否為工作坊帳號

---

## 14.2 確認 Region

```powershell
aws configure get region
```

或：

```powershell
Write-Host $env:AWS_REGION
```

工作坊文件使用的 Region 必須與實際部署 Region 一致。

---

## 14.3 確認目前資源

```powershell
agentcore status
```

先記錄：

- Runtime
- Memory
- Gateway
- Harness
- Evaluation
- Policy Engine
- Config Bundle
- A/B Test

---

## 14.4 確認是否還要保留檔案

刪除雲端資源前，建議保存：

```text
app/
agentcore/
AGENTS.md
README.md
pyproject.toml
uv.lock
```

不要把以下內容提交到 Git：

- AWS Access Key
- AWS Secret Access Key
- AWS Session Token
- Cognito Client Secret
- Access Token
- `.env.local`

---

# 15. Step 1：先停止與封存 A/B Test

如果執行過 Lab 9，A/B Test 必須先停止，才能封存。

停止：

```powershell
agentcore stop ab-test `
  -i <AB_TEST_ID>
```

封存：

```powershell
agentcore archive ab-test `
  -i <AB_TEST_ID>
```

例如：

```powershell
agentcore stop ab-test `
  -i cs-prompt-abtest-XXXXXXXXXX
```

```powershell
agentcore archive ab-test `
  -i cs-prompt-abtest-XXXXXXXXXX
```

---

## 15.1 為什麼要先處理 A/B Test？

正在執行的 A/B Test 仍可能依賴：

- Gateway
- Runtime
- Config Bundle
- Online Evaluation
- Gateway Target

直接刪除底層資源，可能導致依賴關係錯誤。

---

# 16. Step 2：移除 AgentCore 資源

執行：

```powershell
agentcore remove all
```

接著：

```powershell
agentcore deploy
```

這兩個指令的差異：

```text
agentcore remove all
→ 更新本機設定，標記資源要移除

agentcore deploy
→ 實際將刪除變更套用到 AWS
```

可能移除：

- AgentCore Runtime
- AgentCore Memory
- AgentCore Gateway
- Identity / Credential Provider
- Online Evaluation
- Policy Engine
- Harness
- Gateway Targets
- 相關 IAM 與 Deployment Resources

---

# 17. Step 3：確認 AgentCore 資源已移除

再次執行：

```powershell
agentcore status
```

檢查是否仍有：

- Runtime
- Memory
- Gateway
- Harness
- Evaluation
- Policy Engine

也可以查看 CloudFormation：

```powershell
aws cloudformation list-stacks `
  --stack-status-filter `
    CREATE_COMPLETE `
    UPDATE_COMPLETE `
    DELETE_FAILED
```

---

# 18. Step 4：刪除 Prerequisites CloudFormation Stack

工作坊前置 Stack：

```text
agentcore-workshop-prereqs
```

刪除：

```powershell
aws cloudformation delete-stack `
  --stack-name agentcore-workshop-prereqs
```

這個 Stack 可能包含：

- Cognito User Pool
- Cognito App Clients
- Warranty Lambda
- Refund Lambda
- IAM Roles
- SSM Parameters
- OAuth Resource Server
- Workshop Supporting Resources

---

# 19. Step 5：等待 Stack 刪除完成

```powershell
aws cloudformation wait `
  stack-delete-complete `
  --stack-name agentcore-workshop-prereqs
```

這個指令會等待 CloudFormation 完成刪除。

若成功，通常不會輸出大量內容，而是直接結束。

---

# 20. Step 6：驗證 Stack 已刪除

執行：

```powershell
aws cloudformation describe-stacks `
  --stack-name agentcore-workshop-prereqs
```

如果已刪除，通常會看到：

```text
Stack does not exist
```

也可以確認 SSM Parameters 是否不存在：

```powershell
aws ssm get-parameters-by-path `
  --path "/app/customersupport/agentcore/" `
  --recursive
```

---

# 21. 清理失敗的常見原因

## 21.1 A/B Test 還在 Running

先執行：

```powershell
agentcore stop ab-test -i <AB_TEST_ID>
```

再：

```powershell
agentcore archive ab-test -i <AB_TEST_ID>
```

---

## 21.2 CloudFormation 顯示 DELETE_FAILED

查看 Stack Event：

```powershell
aws cloudformation describe-stack-events `
  --stack-name agentcore-workshop-prereqs
```

常見原因：

- Resource 仍被其他服務引用
- IAM 權限不足
- S3 Bucket 非空
- Security Resource 仍有依賴
- Gateway / Runtime 尚未刪除

---

## 21.3 使用錯誤 AWS Account

先執行：

```powershell
aws sts get-caller-identity
```

工作坊臨時 Credential 過期後，可能切換到另一個 Default Profile。

不要在沒有確認 Account ID 的情況下執行：

```powershell
agentcore remove all
```

---

## 21.4 使用錯誤 Region

AgentCore 資源與 CloudFormation Stack 都具有 Region 範圍。

確認：

```powershell
$env:AWS_REGION
$env:AWS_DEFAULT_REGION
aws configure get region
```

---

## 21.5 Preview CLI 指令不同

Lab 8、Lab 9 使用 Preview 功能，CLI 版本可能改變。

先查看：

```powershell
agentcore remove --help
```

```powershell
agentcore stop ab-test --help
```

```powershell
agentcore archive ab-test --help
```

---

# 22. 建議的安全清理順序

```text
1. 確認 AWS Account 與 Region
2. 備份本機 Project
3. 停止 A/B Test
4. 封存 A/B Test
5. 停止不需要的 Evaluation
6. 移除 AgentCore Resources
7. agentcore deploy 套用刪除
8. agentcore status 驗證
9. 刪除 Prerequisites CloudFormation Stack
10. 等待 Stack Delete Complete
11. 檢查 CloudFormation 與 SSM
12. 確認沒有持續產生費用的資源
```

---

# 23. 建議額外檢查的 AWS 資源

工作坊清理後，可再到 AWS Console 檢查：

- CloudFormation
- AgentCore Runtime
- AgentCore Gateway
- AgentCore Memory
- Cognito
- Lambda
- IAM Roles
- SSM Parameter Store
- CloudWatch Logs
- S3
- ECR
- CloudWatch Evaluation / Observability

不要看到 Console 空白就立刻放心；請先確認 Region，AWS Console 最擅長用錯 Region 製造一種「宇宙和平」的錯覺。

---

# 24. 工作坊最重要的工程觀念

## 24.1 Agent 不只是 LLM

完整 Agent 系統包含：

```text
Model
＋
Prompt
＋
Tools
＋
Memory
＋
Identity
＋
Policy
＋
Observability
＋
Evaluation
＋
Interface
＋
Operations
```

---

## 24.2 Tool Calling 不等於 Governance

Agent 會呼叫 Tool，只代表能力存在。

還需要：

- Authentication
- Authorization
- Cedar Policy
- Backend Validation
- Audit Log
- Human Approval
- Idempotency

---

## 24.3 Evaluation 不等於 Ground Truth

LLM-as-a-Judge 是品質訊號，不是最終真理。

仍需要：

- 人工抽查
- 業務規則測試
- 固定 Evaluation Set
- 邊界案例
- Security Test
- Regression Test

---

## 24.4 A/B Test 不等於只看平均分數

正式判斷還要看：

- P-Value
- Sample Size
- Effect Size
- Correctness
- Latency
- Token Cost
- Error Rate
- User Satisfaction

---

## 24.5 平台抽象不代表不需要理解底層

AgentCore CLI 幫你處理大量基礎設施，但你仍需要理解：

- AWS Credential
- IAM
- Region
- Cognito JWT
- OAuth
- Gateway
- CloudFormation
- Session
- Trace
- Cost
- Resource Lifecycle

平台只是幫你少寫 YAML，不會替你承擔誤刪 Production 的心理陰影。

---

# 25. 後續可以繼續學什麼？

## 25.1 AgentCore Samples

可尋找：

- 不同 Framework
- 不同 Model
- 不同 Tool Integration
- Memory Pattern
- Gateway Pattern
- Runtime Pattern
- Policy Pattern

---

## 25.2 AgentCore CLI 進階功能

可繼續研究：

- VPC Networking
- Custom Container
- Private Network
- Multiple Runtime
- Environment Configuration
- Policy Engine
- Harness
- Config Bundle
- CI/CD Deployment

---

## 25.3 AgentCore 官方文件

建議深入理解：

- Runtime
- Memory
- Gateway
- Identity
- Observability
- Evaluations
- Policy
- Harness
- Optimization
- Pricing
- Quotas
- Security Best Practices

---

# 26. 最後檢查清單

## 專案成果

- [ ] Lab 1～9 文件已保存
- [ ] 本機 Project 已備份
- [ ] `main.py` 已保存
- [ ] `agentcore.json` 已保存
- [ ] `harness.json` 已保存
- [ ] `pyproject.toml` 與 `uv.lock` 已保存
- [ ] 沒有保存敏感 Credential

## 雲端清理

- [ ] AWS Account 已確認
- [ ] AWS Region 已確認
- [ ] A/B Test 已停止
- [ ] A/B Test 已封存
- [ ] `agentcore remove all` 已執行
- [ ] `agentcore deploy` 已執行
- [ ] `agentcore status` 已確認
- [ ] Prerequisites Stack 已刪除
- [ ] Stack Delete Complete 已等待
- [ ] Cognito 已移除
- [ ] Lambda 已移除
- [ ] SSM Parameters 已移除
- [ ] CloudWatch / S3 / ECR 已額外檢查

---

# 27. 一句話總結

這個工作坊的核心不是單純教你建立一個 Chatbot，而是完整示範：

```text
如何把一個 Agent Prototype
逐步變成具有記憶、工具、安全、治理、監控、
品質評估、使用者介面與持續優化能力的正式系統。
```

最終形成的 Agent 工程循環是：

```text
Build
→ Connect
→ Secure
→ Observe
→ Evaluate
→ Govern
→ Optimize
→ Operate
→ Clean Up
```
