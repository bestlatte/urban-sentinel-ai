# 加分項：把 A2 Orchestrator 部署到 Bedrock AgentCore Runtime

> 狀態：P1（加分項，核心 Demo 路徑完成、驗收測試全過後才做）
> 依據：`AWS服務選型建議.md`「Day3 部署 AgentCore Runtime」「風險：AgentCore部署卡住→回到FastAPI直接boto3/Strands呼叫Bedrock」、`00-tech-stack.md` §2「AgentCore Runtime 僅為核心完成後的加分項，核心流程不得依賴它」。
> CLI 操作參考：`AgentCore_Runtime_部署參考教學.md`（同資料夾，AWS 官方客服機器人範例教學，操作步驟通用，程式內容需替換成本專案的 agent）。

---

> ## [2026-08-01 修訂摘要]
>
> 本文件 v1 把部署對象定為 **W1 What-if Agent**，且 §3.2 的範例程式有三處會直接失敗。本次依實作結果全面改寫，主要變更：
>
> | 項目 | v1 | 現況 |
> |---|---|---|
> | 部署對象 | W1 What-if Agent | **A2 Orchestrator**（決策編排才是本專案的 agentic 核心） |
> | CLI | `agentcore create/dev/deploy` | 不變，但**官方套件已從 pip 改為 npm**（見 §2） |
> | 程式路徑 | `src/agent.py` | 該檔不存在，實際是 `src/agent/` 套件 |
> | 範例 entrypoint | `from ... import WHATIF_AGENT` 後直接呼叫 | `WHATIF_AGENT` 在 import 時是 `None`，該寫法必 crash（見 §6） |
> | 打包方式 | 未說明 | Full 自足部署，見 §3 |

## 1. 範圍界定（只做這件事，不做別的）

把已經寫好的 A2 Orchestrator 部署到 AgentCore Runtime，展示「不只是本機 demo」。教學資料夾裡另外 9 份 Lab（Memory、Gateway、Session/Cognito、Observability、評估、Chat Interface、Policy、Zero-code、A/B測試）**團隊文件從未提過要做**，不在本次範圍內。

明確不做（沿用 `00-tech-stack.md` §2 的禁用清單）：

- AgentCore Memory（W2 的 `session/session_manager.py` 維持現有記憶體 dict 設計）
- AgentCore Gateway（工具維持現有 Strands 註冊方式，不包成 Gateway MCP Tool）
- Cognito JWT 保護（`00-tech-stack.md` §2 明文禁止登入/角色權限系統）
- 評估、Chat Interface、Policy、Zero-code、A/B測試
- Observability 不主動設定——但 `agentcore deploy` 會自動啟用 OpenTelemetry，這是 CLI 行為，不是我們額外做的事

### 1.1 為什麼從 W1 改成 A2

W1 是「使用者問一句、Agent 答一句」的對話 Agent，部署上雲展示的是 Bedrock 對話能力。A2 才是本專案真正的 agentic 價值所在（SPEC-O2 §1「事件為自然語言描述、類型開放，需要理解與規劃；此處為 agentic 價值所在」）：LLM 規劃工具序列 → 三層護欄驗證 → 決定性模組執行 → 產出完整 `DecisionResult`。

部署 A2 的展示效果是：一行 `agentcore invoke` 就在雲端跑完 SPEC-O1 的七階段決策週期，並回傳與本機**逐位元相同**的黃金值。

## 2. 前置條件

- 核心 Demo 路徑（`INDEX.md` 建置順序階段 0～6）全部完成且驗收測試通過。
- AWS Credential、Model Access、Region（`us-west-2`）已依 `AWS服務選型建議.md` 開通。
- **AgentCore CLI 走 npm，不是 pip**：

  ```powershell
  npm install -g @aws/agentcore
  agentcore --version        # 驗證，本次實作用的是 0.25.0
  ```

  pip 的 `bedrock-agentcore-starter-toolkit` 執行時會印出：

  > ⚠️ Recommendation: The Starter Toolkit CLI is no longer supported.
  > Please use the AgentCore CLI (@aws/agentcore) ... New Bedrock AgentCore features are only accessible in the AgentCore CLI.

  兩者指令集不同（pip 版是舊的 `configure`/`launch`），**不要混用**。

- Python 端套件：`strands-agents`、`bedrock-agentcore`（已列入 repo `pyproject.toml`）。
- `uv`：AgentCore CLI 用它管 Python 依賴，缺了 `agentcore create` 會直接中止。

  ```powershell
  pip install uv
  ```

### 2.1 已知依賴衝突（會打壞主流程，務必處理）

安裝 `strands-agents` 會透過 `mcp → sse-starlette` 把 `starlette` 升到 1.x，而較舊的 `fastapi` 要求 `starlette < 0.50`，`main.py` 會在 import 階段就拋
`TypeError: Router.__init__() got an unexpected keyword argument 'on_startup'`。

解法是升級 FastAPI（**不要**降 starlette，那會反過來打壞 strands 的 MCP 相依）：

```powershell
pip install --upgrade fastapi "uvicorn[standard]"
pip check        # 應回 No broken requirements found.
```

## 3. 打包策略：Full 自足部署

### 3.1 為什麼需要 build 腳本

AgentCore Runtime 的 `codeLocation` 是 `app/<Name>/`，執行時 `from src...` 只在該目錄底下解析得到。但本文件 §1 又要求骨架建在**獨立目錄**、不得污染 `00-tech-stack.md` §3 的固定目錄結構——「隔離」與「import 得到」互相拉扯。

解法：repo 維持唯一真實來源，部署前用腳本把檔案**複製**進 `codeLocation`。

```powershell
python scripts/build_agentcore_package.py
```

產出結構（`src/loaders.py` 與 `src/reporting.py` 都以 `Path(__file__).parents[1]` 定位 `data/` 與 `prompts/`，所以三者必須平行擺放，複製後不需改任何路徑程式碼）：

```text
urban-sentinel-agentcore/UrbanSentinelOrch/     # repo 外，不污染固定目錄結構
├─ agentcore/          # CLI 設定 + CDK 專案
└─ app/UrbanSentinelOrch/
   ├─ main.py          # entrypoint（手寫）
   ├─ pyproject.toml   # 依賴（手寫）
   ├─ src/             # ← build 腳本產出，排除 ws_manager.py
   ├─ data/            # ← build 腳本產出
   └─ prompts/         # ← build 腳本產出
```

`app/<Name>/src|data|prompts` 全部是產出物，**不得手動編輯**，下次執行會整個覆蓋。

### 3.2 排除清單與相依檢查

`src/ws_manager.py` 匯入 `fastapi.WebSocket`，是 `src/` 底下唯一相依 web framework 的模組。AgentCore Runtime 不跑 FastAPI，且 `orchestrator` 對推播是以 `ws_broadcaster=None` 參數注入，雲端本來就不需要它。

build 腳本會在複製後用 AST 掃描產出的 `src/`，若殘留 `fastapi`／`uvicorn`／`starlette` 的 import 就直接失敗——這種錯誤只會在雲端冷啟動時才炸，本地測不出來，所以擋在打包階段。

部署包實際依賴只有四項之外加兩項：骨架自帶 `aws-opentelemetry-distro`／`bedrock-agentcore`／`botocore[crt]`／`mcp`／`strands-agents`，本專案再加 `pydantic>=2`（`src/models.py`）與 `boto3`（`reporting._invoke_bedrock_converse`）。

**不含 `networkx` 與 `pandas`**——實測全專案零 import（`networkx` 與 `00-tech-stack.md` §1 的技術棧宣告不一致，是既有落差，見 repo `pyproject.toml` 註記）。

### 3.3 LLM 只規劃、Runtime 執行

這是本次部署最重要的分層，跟 SPEC-O2 §3.1 一致：

```text
AgentCore Runtime（自足容器）
├── A2 LLM 規劃器  → 只輸出 ToolPlan JSON，不執行工具、不產生數值
└── Python 決定性模組 → 收到 ToolPlan 後真的執行 rules / routing / ETE
        ↓
   entrypoint 回傳完整 DecisionResult（黃金值與本機相同）
```

因此 Inspector 上**看不到** Strands 的 tool-call trace——這是預期行為，不是壞掉。A2 規劃器刻意以 `tools=[]` 建立（SPEC-O2 §3.1「不執行工具」），展示素材改用 PLAN 留痕裡的工具序列與回傳的 `DecisionResult`。

## 4. 實作步驟

1. 建立骨架（repo 外的獨立目錄）：

   ```powershell
   agentcore create `
     --output-dir C:\Users\<you>\urban-sentinel-agentcore `
     --project-name UrbanSentinelOrch --name UrbanSentinelOrch `
     --type create --language Python `
     --framework Strands --model-provider Bedrock --memory none `
     --protocol HTTP --build CodeZip --network-mode PUBLIC `
     --skip-install --skip-python-setup --skip-git
   ```

   > 注意：`--defaults` 會建出 **harness** 專案（zero-code，Lab8 那套），不是我們要的 Strands runtime agent，務必顯式帶 `--framework Strands`。

2. 同步程式與資料：`python scripts/build_agentcore_package.py`
3. 確認 `app/UrbanSentinelOrch/main.py` 的 entrypoint 呼叫的是 `orchestrator.handle_incident()`，且 `pyproject.toml` 已含 `pydantic` 與 `boto3`。
4. `agentcore dev` 本機測試，Inspector 送 `{"prompt": "TPE_2026_ACC_001"}`。
5. `agentcore deploy` → `agentcore status` → `agentcore invoke` 驗證雲端可呼叫。
6. **不修改** repo 的 `main.py`／`orchestrator.py` 對外呼叫方式——`POST /api/incidents/evaluate` 走的仍是本機 `handle_incident()`，AgentCore Runtime 只是額外提供「這套編排也能在雲端獨立執行」的展示能力。

### 4.1 呼叫方式

```powershell
agentcore invoke '{"prompt": "TPE_2026_ACC_001"}'   # 跑完整決策週期
agentcore invoke '{"prompt": "list"}'               # 列出可用事件
```

## 5. 保底原則（不可違反）

- 部署失敗、逾時或 Demo 現場網路不穩 → 直接不展示這個加分項，主流程完全不受影響（repo `main.py` 沒有依賴它）。
- 不得為了整合 AgentCore Runtime 而改動 `orchestrator.py` 對 `POST /api/incidents/evaluate` 的既有介面——這條規則本身就是 `00-tech-stack.md` §2「核心流程不得依賴它」的具體落實。
- 部署包與 repo 共用同一份 `src/`（靠 build 腳本複製），所以雲端與本機的決定性結果必然一致；**禁止**手改 `app/<Name>/src/` 來讓雲端「單獨修好」某個問題。

## 6. v1 範例程式的三個缺陷（留存備查）

v1 §3.2 給的 entrypoint 範例如下，三處都會失敗：

```python
from src.agent.whatif_agent import WHATIF_AGENT  # ← 缺陷 a

app = BedrockAgentCoreApp()

@app.entrypoint
def invoke(payload):                              # ← 缺陷 c
    question = payload.get("prompt", "")
    return str(WHATIF_AGENT(question))            # ← 缺陷 b
```

- **(a)** `WHATIF_AGENT` 是延遲初始化的模組層級變數，import 當下的值是 `None`（`whatif_agent.py` 的 `WHATIF_AGENT = None`）。
- **(b)** 因此 `WHATIF_AGENT(question)` 會拋 `TypeError: 'NoneType' object is not callable`。正確入口是 `process_whatif(context)` 或 `process_whatif_request(...)`，且前者收的是 `W1Context` 而非字串。
- **(c)** 骨架產生的 entrypoint 簽章是 `async def invoke(payload, context)`，兩個參數；只寫 `payload` 會對不上。

## 7. Definition of Done

- [x] `agentcore create` 產生的專案骨架獨立於 repo，不污染固定目錄結構
- [x] Entrypoint 呼叫的是本專案 `orchestrator.handle_incident()`，不是教學範例的客服工具邏輯
- [x] build 腳本可重複執行，且有相依檢查擋住 fastapi 誤入部署包
- [x] 本機以保底模式驗出黃金值（主 RD_TPE_004 / 次 RD_TPE_005 / ETE 90 分 / 恢復 2026-05-20 23:40）
- [ ] `agentcore deploy` 成功、`agentcore invoke` 可驗證雲端回應 ← **待有效 AWS 憑證**
- [x] repo `main.py` 的 `POST /api/incidents/evaluate` 呼叫鏈完全沒有變動
