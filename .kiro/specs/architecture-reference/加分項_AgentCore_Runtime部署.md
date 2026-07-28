# 加分項：把 W1 的 Strands Agent 部署到 Bedrock AgentCore Runtime

> 狀態：P1（加分項，核心 Demo 路徑完成、驗收測試全過後才做）
> 依據：`AWS服務選型建議.md`「Day3 部署 AgentCore Runtime」「風險：AgentCore部署卡住→回到FastAPI直接boto3/Strands呼叫Bedrock」、`00-tech-stack.md` §2「AgentCore Runtime 僅為核心完成後的加分項，核心流程不得依賴它」。
> CLI 操作參考：`AgentCore_Runtime_部署參考教學.md`（同資料夾，AWS 官方客服機器人範例教學，操作步驟通用，程式內容需替換成本專案的 `agent.py`）。

---

## 1. 範圍界定（只做這件事，不做別的）

團隊文件裡對 AgentCore 的**唯一**引用是「把已經寫好的 Strands Agent 部署到 AgentCore Runtime，展示不只是本機 demo」。教學資料夾裡另外 9 份 Lab（Memory、Gateway、Session/Cognito、Observability、評估、Chat Interface、Policy、Zero-code、A/B測試）**團隊文件從未提過要做**，不在本次範圍內，不要一併實作。

明確不做（沿用 `00-tech-stack.md` §2 的禁用清單）：
- AgentCore Memory（W2 的 `session/session_manager.py` 維持現有記憶體 dict 設計，不換成 Memory）
- AgentCore Gateway（K3/W1 的工具維持現有 Strands `@tool` 直接註冊，不包成 Gateway MCP Tool）
- Cognito JWT 保護（`00-tech-stack.md` §2 明文禁止登入/角色權限系統）
- Observability/CloudWatch、評估、Chat Interface、Policy、Zero-code、A/B測試

## 2. 前置條件

- 核心 Demo 路徑（`INDEX.md` 建置順序階段 0～6）全部完成且驗收測試通過。
- `src/agent.py` 已經是可運作的 Strands Agent（W1 What-if 邏輯）。
- AWS Credential、Model Access、Region（`us-west-2`）已依 `AWS服務選型建議.md` 開通。

## 3. 實作步驟（改寫自教學文件，替換成本專案內容）

1. 在**獨立目錄**（不是 `project/` 根目錄，避免 `agentcore create` 產生的骨架檔案跟固定目錄結構衝突）跑 `agentcore create`，建立 AgentCore 專案骨架。
2. 把骨架裡的 entrypoint 程式碼替換成呼叫本專案 `src/agent.py` 的 `process_whatif()` / `WHATIF_AGENT`，而不是教學範例的客服工具：
   ```python
   from bedrock_agentcore.runtime import BedrockAgentCoreApp
   from src.agent.whatif_agent import WHATIF_AGENT  # 沿用既有 Agent 實例，不重新定義

   app = BedrockAgentCoreApp()

   @app.entrypoint
   def invoke(payload):
       question = payload.get("prompt", "")
       return str(WHATIF_AGENT(question))
   ```
3. `agentcore dev` 本機測試 Inspector 可正常對話。
4. `agentcore deploy` 部署至 AWS；`agentcore status` 確認狀態；`agentcore invoke "..."` 驗證雲端可呼叫。
5. **不修改** `main.py`／`orchestrator.py` 對 W1 的既有呼叫方式——`POST /api/what-if` 走的仍是本機 `process_whatif_request()`（見 `m3-bedrock-advisor/W1-whatif-agent/design.md` 第十節），AgentCore Runtime 只是額外提供「這個 Agent 也能在雲端獨立呼叫」的展示能力，不取代現有呼叫鏈，避免 Demo 當天依賴額外的雲端部署環節。

## 4. 保底原則（不可違反）

- 部署失敗、逾時或 Demo 現場網路不穩 → 直接不展示這個加分項，主流程完全不受影響（`main.py` 本來就沒有依賴它）。
- 不得為了整合 AgentCore Runtime 而改動 `src/agent.py` 對 `orchestrator.py`/`POST /api/what-if` 的既有介面——這條規則本身就是 `00-tech-stack.md` §2「核心流程不得依賴它」的具體落實。

## 5. Definition of Done

- [ ] `agentcore create` 產生的專案骨架獨立於 `project/` 主結構，不污染固定目錄
- [ ] Entrypoint 呼叫的是本專案 `WHATIF_AGENT`，不是教學範例的客服工具邏輯
- [ ] `agentcore deploy` 成功、`agentcore invoke` 可驗證雲端回應
- [ ] `main.py` 的 `POST /api/what-if` 呼叫鏈完全沒有變動，核心流程不依賴這次部署是否成功
