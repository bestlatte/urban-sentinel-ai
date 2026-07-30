# Amazon Bedrock AgentCore Lab 5：評估 Agent 品質

## 0. 本 Lab 要完成什麼？

前面的 Lab 已經完成：

- Lab 1：建立 Agent Prototype
- Lab 2：加入跨 Session Memory
- Lab 3：使用 Gateway 集中管理 Tool
- Lab 4：加入 Cognito JWT、Session 與 Observability

本 Lab 會加入 **AgentCore Evaluations**，讓系統持續評估 Agent 的回答品質。

完成後，你可以：

1. 建立 Online Evaluation
2. 使用內建 Evaluator 評估 Agent
3. 自動抽樣正式環境互動
4. 對歷史 Trace 執行 On-Demand Evaluation
5. 透過 CLI 與 CloudWatch 查看分數
6. 根據低分結果調整 Prompt、Tool 與資料

---

# 1. 先理解 AgentCore Evaluations

AgentCore Evaluations 用來回答三個問題：

```text
Agent 有沒有完成使用者目標？
Agent 回答是否正確？
Agent 有沒有選對 Tool？
```

本 Lab 使用三個內建 Evaluator：

| Evaluator | 評估內容 |
|---|---|
| `Builtin.GoalSuccessRate` | Agent 是否完成使用者目標 |
| `Builtin.Correctness` | 回答內容是否正確 |
| `Builtin.ToolSelectionAccuracy` | Agent 是否選擇正確 Tool |

---

# 2. Online Evaluation 如何運作？

Online Evaluation 會持續監控已部署的 Agent。

流程：

```text
Agent 收到使用者請求
    ↓
產生 Trace
    ↓
依 Sampling Rate 抽樣
    ↓
Evaluator 評估互動
    ↓
結果寫入 CloudWatch
    ↓
查看趨勢與低分 Session
```

三個重要概念：

| 概念 | 說明 |
|---|---|
| Sampling | 決定多少比例的 Session 會被評估 |
| Evaluation | 使用內建或自訂 Evaluator 判斷品質 |
| Monitoring | 在 CloudWatch 查看評估結果與趨勢 |

---

# 3. 前置條件

開始前請確認：

- 已完成 Lab 1～4
- `CustomerSupport` Runtime 已部署
- Runtime 已啟用 Cognito JWT
- Gateway 可正常呼叫
- CloudWatch Observability 已有 Trace
- AWS Credential 尚未過期
- Terminal 位於 `CustomerSupport` 專案根目錄

---

# 4. Step 1：建立 Online Evaluation

在 Kiro Terminal 執行：

```powershell
agentcore add online-eval `
  --name QualityMonitor `
  --runtime CustomerSupport `
  --evaluator `
    Builtin.GoalSuccessRate `
    Builtin.Correctness `
    Builtin.ToolSelectionAccuracy `
  --sampling-rate 100 `
  --enable-on-create
```

也可以寫成單行：

```powershell
agentcore add online-eval --name QualityMonitor --runtime CustomerSupport --evaluator Builtin.GoalSuccessRate Builtin.Correctness Builtin.ToolSelectionAccuracy --sampling-rate 100 --enable-on-create
```

成功後應看到：

```text
Added online eval 'QualityMonitor'
```

---

## 4.1 參數說明

| 參數 | 用途 |
|---|---|
| `--name QualityMonitor` | Evaluation 設定名稱 |
| `--runtime CustomerSupport` | 指定要評估的 Runtime |
| `--evaluator` | 指定評估器 |
| `--sampling-rate 100` | 評估 100% 互動 |
| `--enable-on-create` | 部署後立即啟用 |

---

## 4.2 Sampling Rate 怎麼設定？

本工作坊使用：

```text
100%
```

代表每一筆互動都評估。

正式環境通常可考慮：

```text
10%～20%
```

原因：

- 降低評估成本
- 減少處理量
- 仍能掌握整體品質趨勢

建議：

| 情境 | 建議 Sampling Rate |
|---|---:|
| 開發測試 | 100% |
| 小規模試營運 | 50%～100% |
| 正式環境 | 10%～20% |
| 高風險業務 | 視需求提高 |

> Sampling Rate 並不是越高越專業。100% 只是「什麼都看」，帳單也會很誠實地什麼都記。

---

# 5. Step 2：部署 Evaluation 設定

執行：

```powershell
agentcore deploy -y -v
```

CLI 會把 Online Evaluation 與既有資源一起部署。

部署完成後，Evaluator 會開始監控新的互動。

---

## 5.1 確認狀態

```powershell
agentcore status
```

確認：

```text
QualityMonitor
```

狀態為：

```text
ENABLED
```

如果顯示：

```text
DISABLED
```

執行：

```powershell
agentcore resume online-eval QualityMonitor
```

---

# 6. Step 3：確認 Cognito Token

因為 Lab 4 已保護 Runtime，所以測試時必須帶入有效 Token。

如果目前 `$TOKEN` 仍存在且未過期，可以跳過這一步。

---

## 6.1 取得 Cognito Pool ID

```powershell
$COGNITO_POOL_ID = aws ssm get-parameter `
  --name "/app/customersupport/agentcore/pool_id" `
  --query "Parameter.Value" `
  --output text
```

---

## 6.2 取得 Web Client ID

```powershell
$COGNITO_WEB_CLIENT_ID = aws ssm get-parameter `
  --name "/app/customersupport/agentcore/web_client_id" `
  --query "Parameter.Value" `
  --output text
```

---

## 6.3 取得 Access Token

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

不要把 Token 公開或提交到 Git。

---

# 7. Step 4：產生測試互動

建立測試 Session：

```powershell
$SESSION_EVAL = [guid]::NewGuid().ToString()
```

本 Lab 建議產生多種類型的問題，讓 Evaluator 有足夠資料可評估。

---

## 7.1 商品資訊問題

```powershell
agentcore invoke `
  "What can you tell me about the Smart Watch? What's the price and warranty?" `
  --session-id $SESSION_EVAL `
  --bearer-token "$TOKEN" `
  --stream
```

此問題可觀察：

- 是否呼叫商品查詢 Tool
- 是否呼叫 Warranty Tool
- 是否整合多個 Tool 結果
- 回答是否正確

---

## 7.2 退貨政策問題

```powershell
agentcore invoke `
  "I bought headphones last week but they're not working. What's the return policy for audio products?" `
  --session-id $SESSION_EVAL `
  --bearer-token "$TOKEN" `
  --stream
```

此問題可觀察：

- 是否選擇 `get_return_policy`
- 是否辨識類別為 `audio`
- 是否正確回答退貨期限與條件

---

## 7.3 Warranty Gateway 問題

```powershell
agentcore invoke `
  "Check the warranty status for product PROD-001" `
  --session-id $SESSION_EVAL `
  --bearer-token "$TOKEN" `
  --stream
```

此問題可觀察：

- 是否選擇 Gateway Tool
- 是否呼叫 `check_warranty`
- 是否傳入正確 `product_id`
- 是否正確解讀 Lambda 結果

---

## 7.4 多工具問題

```powershell
agentcore invoke `
  "I want to return my USB-C Hub. What's the policy, and can you check if it's still under warranty?" `
  --session-id $SESSION_EVAL `
  --bearer-token "$TOKEN" `
  --stream
```

此問題可觀察：

- 是否先查商品資訊
- 是否辨識商品類別
- 是否查詢退貨政策
- 是否呼叫 Warranty Gateway
- 是否整合多工具結果

---

## 7.5 Agent 能力問題

```powershell
agentcore invoke `
  "What kind of support can you provide? List your capabilities." `
  --session-id $SESSION_EVAL `
  --bearer-token "$TOKEN" `
  --stream
```

此問題可觀察：

- Agent 是否正確描述能力
- 是否誇大不存在的 Tool
- 是否符合 System Prompt

---

# 8. 等待 Evaluation 結果

Online Evaluation 通常不是立即完成。

完成測試後，等待數分鐘：

```powershell
Start-Sleep -Seconds 180
```

如果 CloudWatch 暫時沒有資料，不代表失敗，可能只是還在處理。

---

# 9. Step 5：執行 On-Demand Evaluation

除了持續執行的 Online Evaluation，也可以對歷史 Trace 主動發起評估。

執行：

```powershell
agentcore run eval `
  --runtime CustomerSupport `
  --evaluator `
    Builtin.GoalSuccessRate `
    Builtin.Correctness `
  --days 1
```

這代表：

```text
評估 CustomerSupport
＋
使用 GoalSuccessRate 與 Correctness
＋
分析最近 1 天的 Trace
```

---

## 9.1 Online Evaluation 與 On-Demand Evaluation 差異

| 類型 | 用途 |
|---|---|
| Online Evaluation | 自動持續評估新的互動 |
| On-Demand Evaluation | 手動評估過去的 Trace |

適用情境：

### Online Evaluation

- 正式環境監控
- 長期趨勢追蹤
- 自動抽樣
- 持續品質檢查

### On-Demand Evaluation

- 修改 Prompt 後回頭分析
- 測試新 Tool Description
- 比較版本前後差異
- 臨時調查特定時間範圍

---

# 10. Step 6：透過 CLI 查看結果

## 10.1 查看歷史 Evaluation Run

```powershell
agentcore evals history `
  --runtime CustomerSupport `
  --limit 5
```

可以查看最近幾次評估執行結果。

---

## 10.2 查看 Online Evaluation Logs

```powershell
agentcore logs evals `
  --runtime CustomerSupport `
  --since 30m
```

可用來確認：

- Evaluator 是否執行
- 是否有處理錯誤
- 評估資料是否成功寫入
- 是否因 Trace 不足而沒有結果

---

# 11. Step 7：在 CloudWatch 查看結果

進入 AWS CloudWatch Console。

路徑：

```text
GenAI Observability
→ Bedrock AgentCore
→ CustomerSupport
→ DEFAULT Endpoint
→ Evaluations
```

可以查看：

- Goal Success Rate
- Correctness
- Tool Selection Accuracy
- 評估趨勢
- Session 分數
- 低分互動
- 評估詳細資料

---

# 12. 三個 Evaluator 要怎麼看？

## 12.1 Goal Success Rate

評估：

```text
Agent 最後有沒有真正完成使用者的需求？
```

例如使用者問：

```text
我要退 USB-C Hub，退貨規則是什麼？保固還有效嗎？
```

Agent 必須同時回答：

- 退貨政策
- 保固狀態

只回答其中一半，可能 Goal Success 分數不高。

---

## 12.2 Correctness

評估：

```text
回答內容是否正確？
```

可能導致低分的情況：

- 商品價格錯誤
- 保固日期錯誤
- 退貨期限錯誤
- Tool 回傳正確，但 Agent 整理錯誤
- 模型自行補充不存在資訊

---

## 12.3 Tool Selection Accuracy

評估：

```text
Agent 是否使用正確 Tool？
```

例如：

| 問題 | 正確 Tool |
|---|---|
| 商品價格 | `get_product_info` |
| 退貨政策 | `get_return_policy` |
| Warranty | `check_warranty` |
| 網路疑難排解 | Exa AI MCP |

低分可能代表：

- Tool Description 不清楚
- Tool 名稱太模糊
- Tool 功能重疊
- System Prompt 沒有明確要求
- Agent 靠模型猜測而沒用 Tool

---

# 13. Step 8：判讀分數

工作坊提供的基本參考：

| 分數 | 解讀 | 建議 |
|---|---|---|
| 80%～100% | 表現優良 | 持續監控 |
| 60%～80% | 尚可但可改善 | 查看低分 Session |
| 低於 60% | 需要處理 | 找出根本原因 |

---

## 13.1 不要只看平均分數

例如平均 Correctness 為：

```text
85%
```

看起來很好，但可能是：

```text
商品查詢：100%
退貨政策：100%
Warranty：40%
```

因此應該依問題類型分開看：

- Product
- Return Policy
- Warranty
- Multi-Tool
- Memory
- General Capability

平均值有時像一張很禮貌的地毯，會把問題掃到下面。

---

# 14. Step 9：根據低分改善 Agent

## 14.1 Goal Success Rate 低

可能原因：

- System Prompt 太模糊
- Agent 沒有完成所有子任務
- 多工具問題只呼叫一個 Tool
- 回答缺乏完整結論

改善方式：

- 明確要求完成所有子問題
- 在 Prompt 加入多工具處理規則
- 改善 Tool Description
- 加入回答格式要求

範例：

```text
When a user asks multiple questions, make sure every part
is answered before producing the final response.
```

---

## 14.2 Correctness 低

可能原因：

- 商品資料過期
- Lambda 資料錯誤
- Tool Output 格式不清楚
- Agent 自行猜測
- 相同資訊存在多個來源且互相衝突

改善方式：

- 更新商品資料
- 讓 Tool 回傳結構化內容
- 要求 Agent 優先使用 Tool
- 避免在本機資料與 Gateway 重複保存相同欄位
- 加入「無資料時不要猜」規則

範例：

```text
If a tool does not return the requested information,
state that the information is unavailable.
Do not infer or invent values.
```

---

## 14.3 Tool Selection Accuracy 低

可能原因：

- Tool Name 不清楚
- Description 太短
- 多個 Tool 功能重疊
- Parameter Description 不完整
- System Prompt 沒有說明各 Tool 適用情境

改善方式：

- 使用動詞開頭的 Tool Name
- 說明「何時使用」與「何時不要使用」
- 增加輸入範例
- 拆分過度複雜的 Tool
- 避免兩個 Tool 做相同事情

例如：

```python
@tool
def get_return_policy(product_category: str) -> str:
    """Use this tool when the user asks about return windows,
    return conditions, refunds, exchanges, or defective-item
    return rules for a product category.

    Do not use this tool for warranty status.
    """
```

---

# 15. Step 10：暫停與恢復 Online Evaluation

如果正在維護或想降低成本，可以暫停：

```powershell
agentcore pause online-eval QualityMonitor
```

恢復：

```powershell
agentcore resume online-eval QualityMonitor
```

適合暫停的情況：

- 大量測試資料不需要評估
- Agent 正在維護
- 暫時控制成本
- Evaluation 設定需要調整

---

# 16. 完成後的架構

```text
Client
  │
  │ JWT
  ▼
Amazon Cognito
  │
  ▼
AgentCore Runtime
  ├── Session Management
  ├── Memory
  ├── Local Tools
  ├── Exa AI MCP
  └── Secure Gateway
          │
          ▼
      Warranty Lambda
  │
  ▼
CloudWatch
  ├── Traces
  ├── Logs
  └── Metrics
  │
  ▼
AgentCore Evaluations
  ├── Goal Success Rate
  ├── Correctness
  └── Tool Selection Accuracy
```

---

# 17. AgentCore CLI 背後做了什麼？

執行：

```powershell
agentcore add online-eval
```

主要是更新本機 AgentCore 設定。

執行：

```powershell
agentcore deploy
```

才會把 Evaluation Configuration 部署到 AWS。

部署後，系統會：

1. 根據 Sampling Rate 選擇 Session
2. 對 Sampled Session 執行 Evaluator
3. 使用 LLM-as-a-Judge 方式評估
4. 保存 Evaluation Result
5. 將結果呈現在 CloudWatch
6. 追蹤長期品質趨勢

---

# 18. LLM-as-a-Judge 是什麼？

這些內建 Evaluator 不是單純用：

```text
字串相等
```

判斷答案。

而是使用另一個 LLM，根據：

- 使用者問題
- Agent 回答
- Tool Trace
- Evaluation Criteria

判斷回答品質。

優點：

- 可以評估開放式回答
- 可以分析目標是否完成
- 可以理解 Tool 是否合理
- 不必每題都寫固定答案

限制：

- 評估結果不是絕對真理
- Judge Model 也可能誤判
- 不同問題難度可能影響分數
- 仍需要人工抽查低分與高風險案例

所以：

```text
Evaluation Score
≠ 真實正確率的最終答案
```

它是監控訊號，不是神諭。

---

# 19. 建議的品質改善流程

```text
收集正式互動
    ↓
Online Evaluation
    ↓
找出低分 Session
    ↓
查看 Trace
    ↓
判斷問題來源
    ├── Prompt
    ├── Tool Description
    ├── Tool Output
    ├── 資料
    ├── Model
    └── Gateway / Memory
    ↓
修改
    ↓
重新部署
    ↓
On-Demand Evaluation
    ↓
比較修改前後結果
```

---

# 20. 常見錯誤排查

## 20.1 Evaluation 顯示 DISABLED

執行：

```powershell
agentcore resume online-eval QualityMonitor
```

---

## 20.2 沒有 Evaluation Result

可能原因：

- 尚未產生新互動
- Sampling Rate 太低
- Evaluation 尚未完成
- Trace 尚未寫入
- Runtime 名稱錯誤
- Online Evaluation 未啟用

檢查：

```powershell
agentcore status
```

以及：

```powershell
agentcore logs evals `
  --runtime CustomerSupport `
  --since 30m
```

---

## 20.3 Invoke 回傳 Unauthorized

檢查：

- `$TOKEN` 是否存在
- Token 是否過期
- Cognito 使用者是否存在
- Client ID 是否正確
- 是否帶入 `--bearer-token`

重新取得 Token：

```powershell
$TOKEN = aws cognito-idp initiate-auth `
  --auth-flow USER_PASSWORD_AUTH `
  --client-id $COGNITO_WEB_CLIENT_ID `
  --auth-parameters `
    "USERNAME=workshopuser@example.com,PASSWORD=WorkshopPass1!" `
  --query "AuthenticationResult.AccessToken" `
  --output text
```

---

## 20.4 Tool Selection 分數低

檢查 Trace：

- Agent 實際用了哪個 Tool
- Tool Input 是否正確
- Tool Description 是否清楚
- 是否有功能重疊
- Agent 是否根本沒有呼叫 Tool

---

## 20.5 Correctness 分數低

檢查：

- 原始 Tool Output 是否正確
- Agent 是否誤解 Tool Output
- 資料是否過期
- Prompt 是否允許猜測
- 多個資料來源是否互相衝突

---

## 20.6 CloudWatch 沒有 Evaluation Tab 資料

可能原因：

- 尚未產生足夠互動
- 資料仍在處理
- Region 看錯
- Agent 或 Endpoint 選錯
- Evaluation 未部署成功

---

# 21. 完整操作順序

```text
Step 1
建立 QualityMonitor
    ↓
Step 2
設定三個 Built-in Evaluator
    ↓
Step 3
設定 Sampling Rate
    ↓
Step 4
agentcore deploy
    ↓
Step 5
agentcore status
    ↓
Step 6
取得 Cognito Token
    ↓
Step 7
產生多種測試互動
    ↓
Step 8
等待 Evaluation 處理
    ↓
Step 9
執行 On-Demand Evaluation
    ↓
Step 10
查看 CLI History
    ↓
Step 11
查看 Evaluation Logs
    ↓
Step 12
到 CloudWatch 查看分數
    ↓
Step 13
分析低分 Session
    ↓
Step 14
修改 Prompt、Tool 或資料
    ↓
Step 15
重新部署與評估
```

---

# 22. 指令速查表

| 指令 | 用途 |
|---|---|
| `agentcore add online-eval` | 建立 Online Evaluation |
| `agentcore deploy -y -v` | 部署 Evaluation 設定 |
| `agentcore status` | 查看 Evaluation 狀態 |
| `agentcore resume online-eval` | 啟用 Evaluation |
| `agentcore pause online-eval` | 暫停 Evaluation |
| `agentcore run eval` | 執行 On-Demand Evaluation |
| `agentcore evals history` | 查看歷史 Evaluation Run |
| `agentcore logs evals` | 查看 Evaluation Logs |
| `agentcore invoke` | 產生 Agent 測試互動 |

---

# 23. 最後檢查清單

- [ ] Lab 1～4 已完成
- [ ] Runtime 可正常呼叫
- [ ] JWT Token 有效
- [ ] `QualityMonitor` 已建立
- [ ] 三個 Evaluator 已設定
- [ ] Sampling Rate 已設定
- [ ] Evaluation 已部署
- [ ] Evaluation 狀態為 ENABLED
- [ ] 已產生 Product Query
- [ ] 已產生 Return Policy Query
- [ ] 已產生 Warranty Query
- [ ] 已產生 Multi-Tool Query
- [ ] 已產生 Capability Query
- [ ] 已等待 Evaluation 完成
- [ ] 可查看 Evaluation History
- [ ] 可查看 Evaluation Logs
- [ ] CloudWatch 可看到 Evaluation 分數
- [ ] 已理解三個 Evaluator 的差異
- [ ] 已知道如何根據低分改善 Agent

---

# 24. Lab 1～5 完整成果

| Lab | 完成內容 |
|---|---|
| Lab 1 | Agent Prototype 與 Local Tools |
| Lab 2 | Persistent Memory |
| Lab 3 | AgentCore Gateway |
| Lab 4 | JWT、Session、Observability |
| Lab 5 | Continuous Quality Monitoring |

---

# 25. 一句話總結

本 Lab 的核心流程是：

```text
建立 Online Evaluation
→ 設定品質指標
→ 部署到 AWS
→ 產生 Agent 互動
→ 自動評估 Trace
→ 在 CloudWatch 查看分數
→ 根據低分持續改善 Agent
```
