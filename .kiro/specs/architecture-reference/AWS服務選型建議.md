# AWS 服務選型建議書：智慧交通決策中樞（AWS 競賽版）

> 適用情境：AWS 主辦競賽、5 人團隊、2–3 天可展示原型。
> 搭配文件：`五人團隊分工與Spec開發建議書.md`、`模組間資料流通規格.md`、`diagrams/architecture-aws.svg`（本文件對應的 AWS 服務版架構圖）。
> 資料前提：原始資料為 `data/` 下五個名實相符的 canonical JSON，詳見 `五人團隊分工與Spec開發建議書.md` 第八章。
>
> 核心判斷：這是 **AWS 辦的比賽**，評審會特別看你有沒有用到、而且用得漂亮他們的平台（尤其新的 agentic 服務）。但 2–3 天不能被基礎設施拖死。
> 策略 = **把 AWS 用在刀口上（Bedrock 生態系），其餘維持輕量**，不要把每個資料庫都換成 AWS 託管服務。
>
> **團隊前提：全員為 AWS 新手、沒有實際使用經驗。** 因此本文件以「最少服務、最短路徑、隨時有退路」為原則撰寫，並在第零章提供逐步開通指引。

---

## 零、新手快速上手（動工前先讀完這節）

### 0.1 先建立三個心理準備

1. **只有 1~2 人需要碰 AWS Console。** 其餘三人完全用本機模式開發（見 0.6），不必等雲端好了才動工。這是新手團隊最重要的分工原則。
2. **AWS 的難點不是寫程式，是權限與開通。** 90% 的新手卡關都在「模型沒開通」和「IAM 權限不足」，不是程式邏輯。
3. **任何一步卡超過 30 分鐘就走退路。** 本文件每個服務都標了退路，Demo 絕不能因為某個 AWS 服務沒搞定就整條斷掉。

### 0.2 Region 就選 `us-west-2`（奧勒岡）

新手最常見的災難是「Region 選錯，結果某個服務不支援」。直接選 **`us-west-2`**，理由：

- Strands Agents SDK 的**預設模型就假設 us-west-2**（[Strands PyPI 說明](https://pypi.org/project/strands-agents/)），照文件走最不會出錯。
- S3 Vectors 與 Bedrock Knowledge Bases 在此區都可用（[S3 Vectors 區域清單](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-regions-quotas.html)、[Managed Knowledge Base 公告](https://aws.amazon.com/jp/about-aws/whats-new/2026/06/amazon-bedrock-managed-knowledge-base/)）。
- 教學文章與範例幾乎都用這一區，Google 到的答案能直接套用。

**全員 `AWS_REGION=us-west-2`，不要有人用別區**，否則會出現「我這邊可以你那邊不行」的鬼打牆。

> 內容已改寫並精簡，以符合授權規範。

### 0.3 Day 0 開通步驟（照順序做，約 30~60 分鐘）

**Step 1：開通模型存取權（最容易漏，先做）**

進 AWS Console → 搜尋「Bedrock」→ 左側選單找 **Model access** → 申請開通你要用的模型（建議 Anthropic Claude 系列）。

- 這一步**不開通，後面所有程式都會失敗**，錯誤訊息通常是 `AccessDeniedException`。
- 部分模型需填寫用途申請，可能要等幾分鐘到數小時，**所以務必第一天最早做**。
- Strands 預設使用 Claude Sonnet 系列，AWS 官方教學也以此為前提（[AgentCore 前置需求](https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/runtime-get-started-code-deploy-python.html)）。

**Step 2：設定本機憑證**

```powershell
aws configure
# AWS Access Key ID     → 貼上
# AWS Secret Access Key → 貼上
# Default region name   → us-west-2
# Default output format  → json
```

驗證是否成功：

```powershell
aws sts get-caller-identity
```

有回傳帳號資訊就代表通了。**憑證絕不寫進程式或 commit 進 Git。**

**Step 3：裝套件**

```powershell
pip install strands-agents strands-agents-tools boto3
```

（套件名稱依 [Strands 官方 Quickstart](https://strandsagents.com/docs/user-guide/quickstart/python/)）

**Step 4：跑通第一支程式（Smoke Test）**

先確認「能呼叫模型」，再談其他。建立 `scripts/smoke_bedrock.py`：

```python
from strands import Agent

agent = Agent()  # 預設走 Bedrock Claude
print(agent("用一句話說明什麼是交通飽和度"))
```

跑得出中文回覆，就代表 Region、憑證、模型開通三件事全部正確。**這一步沒過，不要往下做任何 AWS 工作。**

**Step 5：建立費用防護（強烈建議）**

Console → **Billing and Cost Management** → **Budgets** → 建一個月預算（例如 20 USD）並設 email 警示。新手最怕的是不小心開了收費資源忘記關，設個警示就能安心。

### 0.4 新手最容易卡的五個雷

| # | 症狀 | 原因 | 解法 |
|---|---|---|---|
| 1 | `AccessDeniedException` 呼叫模型時 | Model access 沒開通 | 回 Step 1 開通，並確認是**同一個 Region** |
| 2 | `could not find credentials` | 沒跑 `aws configure`，或開了新終端沒讀到設定 | 重跑 `aws sts get-caller-identity` 驗證 |
| 3 | 程式在 A 電腦可跑、B 電腦不行 | 兩人 Region 或憑證不同 | 統一 `us-west-2`，並用 `.env` 對齊設定 |
| 4 | Knowledge Base 建好卻查不到東西 | 資料上傳後**沒點 Sync（同步）** | KB 頁面手動觸發 Sync，等狀態變 Ready |
| 5 | 找不到某個服務或選項 | Console 右上角 Region 不是 us-west-2 | 切換 Region 再找 |

> 第 4 點特別容易卡：KB 不會自動索引新檔案，上傳 S3 後一定要回 KB 按同步。

### 0.5 誰做什麼（AWS 相關分工）

| 人員 | AWS 任務 | 是否需要 Console |
|---|---|---|
| 成員 D | Day 0 開通模型、建 S3 bucket 與 Knowledge Base、寫 Bedrock 呼叫與 Agent | ✅ 需要 |
| 成員 A | 協助排錯、確認 `.env` 與 IAM 權限、整合 Agent 進 FastAPI | ✅ 需要 |
| 成員 B / C / E | **完全不需要碰 AWS Console**，用本機模式開發（見 0.6） | ❌ 不需要 |

這樣安排的理由：新手團隊如果五個人同時去點 Console，很容易互相蓋掉設定、或建出重複資源還搞不清誰建的。

### 0.6 本機保底模式（讓 Demo 永遠不會掛）

在 `.env` 設 `USE_BEDROCK=false` 時，系統必須仍能完整跑完流程：

- **SOP 檢索**：改用本機關鍵字比對 `data/emergency_traffic_sop.json` 的 7 個 section，不呼叫 KB。
- **建議書／簡訊**：改用 Python 固定模板產生（`reporting.py` 的模板本來就要寫）。
- **Agent 工具選擇**：改用「依事件類型查表」的固定流程呼叫工具。

三個決定性工具（規則、路網、ETE）本來就是純 Python，不受影響。所以就算比賽當天 AWS 完全連不上，**你的 Demo 仍能展示完整的感知→決策→通報流程**，只是少了 LLM 的自然語言潤飾。

這不是消極的備案，而是新手團隊的必要保險，也是很好的簡報素材：「我們的事實計算不依賴 LLM，所以可離線驗證」。

---

## 零之二、白話版：專題的哪個部分用什麼工具

新手最需要的是「我做這件事，該用哪個服務」。先看這張表，第一章的技術對照表可以之後再看。

### A. 一句話總覽

```text
資料檔案  → 留在 repo（只有 SOP 上 S3）
SOP 問答  → S3 + Bedrock Knowledge Bases + S3 Vectors
AI 對話   → Bedrock Foundation Model（Claude）
AI 選工具 → Strands Agents SDK
算數字    → 純 Python（NetworkX / 公式），不用 AWS
網站      → 自己的 FastAPI（不用 AWS）
```

### B. 逐項對照

| 專題的哪個部分 | 用什麼工具 | 為什麼 | 新手難度 | 卡住的退路 |
|---|---|---|---|---|
| **五個 JSON 資料檔**（車流／人流／路網／事件） | **不上雲**，留在 repo 由 FastAPI 直接讀 | Demo 只有幾百筆，上雲只會增加麻煩 | ⭐ 無 | — |
| **SOP 條文（要給 AI 查的）** | **Amazon S3** 存放，由 JSON 衍生成文字檔 | S3 是 Knowledge Bases 唯一認得的資料來源 | ⭐⭐ 低 | — |
| **AI 查 SOP 條文（RAG）** | **Bedrock Knowledge Bases** | 自動切段、轉向量、檢索，不用自己寫 RAG | ⭐⭐⭐ 中 | 本機關鍵字比對 7 個 section |
| **SOP 的向量資料庫** | **Amazon S3 Vectors** | 無常駐節點、成本最低，且原生整合 KB | ⭐⭐ 低（建 KB 時選一下而已） | 改選 OpenSearch Serverless |
| **AI 寫建議書／簡訊／解釋** | **Bedrock Foundation Model**（Claude） | 就是「呼叫大語言模型」 | ⭐⭐ 低 | Python 固定模板 |
| **AI 判斷要呼叫哪個工具**（A2） | **Strands Agents SDK** | AWS 官方的 agent 框架，`@tool` 裝飾即可 | ⭐⭐⭐ 中 | 依事件類型查表的固定流程 |
| **算 A/B 級、路線、ETE** | **純 Python**（NetworkX、SOP 公式） | 這些要精準可驗證，不能交給 LLM | ⭐ 無 | — |
| **網站與 API** | **自己的 FastAPI**（本機 `uvicorn`） | 一個 Server 同時給前端、REST、WebSocket | ⭐ 無 | — |
| **即時推播預警** | **FastAPI 內建 WebSocket** | 不需要 AWS 服務 | ⭐⭐ 低 | 前端改輪詢 |
| **多語翻譯**（加分） | **Amazon Translate** 或直接用 Claude | Translate 翻譯較穩定 | ⭐⭐ 低 | 用 Claude 翻 |
| **決策軌跡留存**（加分） | **DynamoDB** 或本機檔案 | 展示可稽核性 | ⭐⭐⭐ 中 | 寫成本機 JSON 檔 |
| **防 LLM 亂改數字**（加分） | **Bedrock Guardrails** | 治理故事好講 | ⭐⭐⭐ 中 | 用 prompt 限制 + Python 覆寫事實 |
| **部署上雲**（加分） | **AgentCore Runtime** | 展示不只是本機 demo | ⭐⭐⭐⭐ 高 | 就用本機跑，Demo 一樣完整 |

### C. 你們實際只需要碰四個 AWS 服務

把加分項全部拿掉，**核心只有這四個**，這就是 Day 0~1 的全部工作：

```text
1. Amazon S3                  → 放 SOP 文字檔
2. Bedrock Model access       → 開通 Claude（Console 點一下）
3. Bedrock Knowledge Bases    → 建一個 KB，向量選 S3 Vectors
4. Strands Agents SDK         → pip 裝套件，寫在 FastAPI 裡
```

其中 **1~3 是在 Console 點選設定**（成員 D 負責，約 1 小時），**4 才是寫程式**。看起來嚇人的清單，實際動手的只有這些。

### D. 常見誤解先講清楚

- **「用 AWS」不等於「要部署到 AWS」。** 你的 FastAPI 跑在自己筆電上，只要它呼叫 Bedrock，就已經是在用 AWS 了。比賽 Demo 用本機跑最穩。
- **不需要為了「看起來有用 AWS」而把資料庫都換成 AWS 服務。** Timestream／Neptune／ElastiCache 這些在架構圖標註「正式版會用」就好，Demo 真的去建只會浪費時間。
- **向量資料庫不是給車流人流資料用的。** 它只存 SOP 條文的語意索引；數值資料一律走 Python 計算。這點新手很常搞混。

---

## 一、模組 → AWS 服務對照表

| 現有模組（見 `diagrams/architecture-json-live.svg`） | 對應 AWS 服務 | 分層 | 說明 |
|---|---|---|---|
| **A2 Orchestrator**（LLM 決定 call 哪個工具） | **Strands Agents SDK → Bedrock；Day3 部署 AgentCore Runtime** | 🔴 核心 | 比賽最大賣點：agentic 工具調度 |
| **K3 RAG 檢索服務** | **Amazon Bedrock Knowledge Bases** | 🔴 核心 | 託管 RAG，免自寫 chunk/embedding |
| **DB4 Vector Store** | **Amazon S3 Vectors**（首選）/ OpenSearch Serverless（備援） | 🔴 核心 | 「S3 當向量庫」成本低、又是新服務亮點 |
| **K1 Embedding Model** | Bedrock 內建 embedding（KB 自動處理） | 🔴 核心 | 由 KB 代管，不用另寫 |
| **LLM_A2 / C1~C3** 解釋與生成 | **Amazon Bedrock Foundation Model**（Claude 等） | 🔴 核心 | 判定結果→自然語言 |
| **C4 多語簡訊** | Bedrock FM **或 Amazon Translate** | 🟡 加分 | Translate 穩、又多用一個 AWS 服務 |
| **R1~R5 路網 / A3 ETE / P4 SOP 規則**（決定性工具） | **AWS Lambda**（Agent 的 Action / @tool） | 🟡 加分 | Demo 可先留在本機 Python |
| **DB5 Decision Log 決策軌跡** | **Amazon DynamoDB** | 🟡 加分 | 展示「可稽核」很有說服力 |
| **DB3 事件記錄庫** | Amazon DynamoDB | ⚪ 選配 | Demo 用記憶體/檔案即可 |
| 資料檔 / SOP 原檔 | **Amazon S3** | 🔴 核心 | KB 資料來源，幾乎零成本 |
| 前端靜態檔 | S3 + CloudFront（或 FastAPI 直接 serve） | ⚪ 選配 | hackathon 用 FastAPI serve 較快 |
| API 入口 + WebSocket 推播 | API Gateway（REST + WebSocket API）+ Lambda | ⚪ 選配 | hackathon 用單一 FastAPI 自帶 `/ws`，不用 API Gateway |
| 安全治理 | **Amazon Bedrock Guardrails** | 🟡 加分 | 防 LLM 竄改條款/數字 |
| **DB1 時序資料庫** | Amazon Timestream | ⚫ 不實作 | 架構圖標註即可，Demo 用檔案 |
| **DB2 路網圖資料庫** | Amazon Neptune | ⚫ 不實作 | NetworkX 記憶體就夠 |
| **DB6 Cache/Redis** | ElastiCache / MemoryDB | ⚫ 不實作 | 跳過 |

分層圖例：🔴 核心（必做） 🟡 加分（時間夠再做） ⚪ 選配（看情況） ⚫ 不實作（僅標註於架構圖）

---

## 二、三個「非用不可、CP 值最高」的 AWS 服務

### 2.1 Bedrock Knowledge Bases + Amazon S3 Vectors（向量資料庫）

對應架構的 **K1 → DB4 → K3** 整條 RAG：

1. SOP 的 source of truth 是 **`data/emergency_traffic_sop.json`**（根層 `{ title, sections[] }`，共 7 個 section）。
   - 因為 KB 索引的是文件而非結構化 JSON，需先由 `sections[]` 衍生出每條一段的 Markdown／純文字檔（`section_number=N` → `SOP-N`），再上傳 **Amazon S3**。
   - 衍生檔只供索引；規則判定一律讀原始 JSON，兩者不可各自修改。
2. 建立一個 **Bedrock Knowledge Base**，向量儲存選 **Amazon S3 Vectors**。
3. KB 會自動做 chunking + embedding + 檢索，你幾乎不用寫 RAG 程式。
4. **上傳新檔案後，一定要回 KB 頁面按 Sync（同步）**，否則查不到內容——這是新手最常卡的一步。

**為什麼選 S3 Vectors（可放心採用）：**

- **可用性已不是風險**：S3 Vectors 已於 2026 年 3 月[擴充至額外 17 個 AWS 區域](https://aws.amazon.com/about-aws/whats-new/2026/03/s3-vectors-expands-17-regions/)，建議的 `us-west-2` 可用；最新清單見[區域與配額文件](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-regions-quotas.html)。
- **原生整合 Knowledge Bases**：官方文件說明 KB 會自動從 S3 取資料、轉成文字區塊、產生 embedding 並寫入向量索引（[S3 Vectors 與 Bedrock KB 整合](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-bedrock-kb.html)），所以在 Console 建 KB 時只是「選一個選項」，不需要額外寫程式或自建基礎設施。
- **成本最低**：不需佈建基礎設施、無常駐節點費用，對只有 7 條 SOP 的用量幾乎可忽略（[S3 Vectors 產品頁](https://aws.amazon.com/s3/features/vectors/)）。
- **對新手友善**：有官方逐步教學可照做（[Getting started with S3 Vectors](https://docs.aws.amazon.com/AmazonS3/latest/userguide/s3-vectors-getting-started.html)）。
- 退場方案仍保留：若真的踩雷，KB 向量儲存改選 **OpenSearch Serverless**，只是會產生常駐節點成本。決策參考可看 [AWS 向量資料庫選型指南](https://docs.aws.amazon.com/pdfs/prescriptive-guidance/latest/choosing-an-aws-vector-database-for-rag-use-cases/choosing-an-aws-vector-database-for-rag-use-cases.pdf)。

> 內容已改寫並精簡，以符合授權規範。

### 2.2 Strands Agents（+ Bedrock / AgentCore）作為 A2 Orchestrator

這正是先前討論「A2 是不是 LLM 決定要 call 哪個工具」的 AWS 官方實作。落實「三層決定」：

```
Agent（LLM 大腦：決定叫哪個工具）              ← 這層是 LLM
   ├─ @tool 路網規劃  (R1~R5, NetworkX)         ← 決定性演算法，算出真答案
   ├─ @tool ETE 計算  (A3, SOP第7條公式)         ← 決定性
   ├─ @tool SOP 規則  (P4)                       ← 決定性
   └─ Knowledge Base 查 SOP 原文 (K3→S3 Vectors) ← 撈事實，不編造
生成建議書/簡訊 (C1~C4)                          ← 這層又是 LLM，只寫字
```

- LLM 只負責「選工具」與「寫字」，**真正的路線/級別/ETE 由決定性工具算出**、SOP 原文由 RAG 撈出——確保精準引用、不亂掰。
- Agent 的 trace 天生可記錄「這次呼叫了哪些工具、依據哪條 SOP」，直接餵 **A4 決策軌跡 → DynamoDB**，可稽核性內建。

**hackathon 實作路線（重要）：**
- 不要一開始就去 console 建 managed Bedrock Agent（設定繁瑣）。
- 用 **Strands Agents SDK 寫在 FastAPI 裡**，工具用 `@tool` 裝飾的 Python 函式。
- 好處：跑在本機、好 debug、Day 1 就能動；且 Strands 可在 **Day 3 原封不動部署到 Bedrock AgentCore Runtime** 當加分項。

Strands 範例骨架：

```python
from strands import Agent, tool

@tool
def plan_routes(incident_id: str) -> dict:
    """避開事故/容量不足/飽和路段，回傳主/次疏散路線與排除理由"""
    ...  # NetworkX 決定性演算法 (R1~R5)

@tool
def calc_ete(road_id: str) -> int:
    """依 SOP 第7條計算 ETE 與預計恢復時間"""
    ...  # (A3)

@tool
def query_sop(question: str) -> str:
    """從 Bedrock Knowledge Base 檢索 SOP 條款原文 (K3)"""
    ...

agent = Agent(
    model="<bedrock-model-id>",
    tools=[plan_routes, calc_ete, query_sop],
    system_prompt="你是交通應變決策編排器，依事件分類與級別呼叫工具，不得自行編造路線/級別/ETE。",
)
```

### 2.3 Amazon S3

放由 `emergency_traffic_sop.json` 衍生的 SOP 索引文件、（可選）前端靜態檔。近乎零成本，且是 Knowledge Base 的資料來源，必用。

五個 canonical JSON 本身留在 repo 由 FastAPI 直接讀取即可，不必為了 Demo 全部搬上 S3。

---

## 三、加分但別擋路（時間夠再做）

| 服務 | 用途 | 效益 |
|---|---|---|
| **Amazon Translate** | C4 多語簡訊直接翻中/英/日/韓 | 比 LLM 翻譯穩、又多用一個 AWS 服務 |
| **Amazon DynamoDB**（DB5） | 寫入每次決策軌跡 | Demo 打開「決策依據面板」很有說服力 |
| **Bedrock Guardrails** | 防 LLM 亂改數字/條款 | 呼應「LLM 不得竄改級別/路線/ETE」原則，治理故事 |
| **AgentCore Runtime** | Day 3 部署 Strands agent | 展示「不只是本機 demo」 |

---

## 四、建議「別碰」的（維持既有判斷）

Timestream / Neptune / ElastiCache / 全套 API Gateway+Lambda serverless / Step Functions
— **在架構圖上標註為「正式版會用」即可，Demo 不要真的建**。

理由：2–3 天內灌資料、調 IAM 權限、除錯的成本，遠大於評分效益。評審看的是 **Bedrock 生態系用得好不好**，不是你有沒有把六個資料庫都上雲。

---

## 五、比賽最佳解 AWS 架構（Demo 版）

```text
瀏覽器 (HTML/CSS/JS Dashboard)
        │ Fetch
        ▼
FastAPI (單一 Python Server) ── boto3 / Strands SDK
        │
        ├─ Strands Agent (=A2，LLM 決定 call 誰) ──► Bedrock FM (Claude)
        │     ├─ @tool 路網規劃 (NetworkX，決定性)
        │     ├─ @tool ETE 計算 (SOP第7條，決定性)
        │     ├─ @tool SOP 規則判定 (P4，決定性)
        │     └─ Bedrock Knowledge Base ──► Amazon S3 Vectors ◄── S3(SOP原文)
        │
        ├─ 生成 (建議書/簡訊) ──► Bedrock FM  (+ Amazon Translate 選配)
        ├─ 決策軌跡 ──► DynamoDB (選配，展示可稽核)
        └─ WebSocket /ws ──► 主動推播預警與決策結果 (FastAPI 自帶)

原始資料：repo 的 data/ 五個 JSON
SOP 索引文件（由 JSON 衍生）：Amazon S3
[Day3 加分] Strands Agent → 部署到 Bedrock AgentCore Runtime
```

**一句話總結：**
`Bedrock FM + Knowledge Bases + S3 Vectors + Strands Agent` 這四件是比賽主軸（把「RAG + agentic 工具調度」講成一個完整故事）；S3 / DynamoDB / Translate 是低成本加分；其餘資料庫服務只在架構圖上標註、不實作。

---

## 六、開賽前 AWS 檢查清單

1. 選定 **Region** 能呼叫目標 **Bedrock Model**（確認模型已在該 region 開通存取）。
2. 建 KB 時向量儲存選 **S3 Vectors**（`us-west-2` 已支援，不需另行確認）；若建立失敗才改用 OpenSearch Serverless。
3. **Knowledge Base** 能檢索 SOP 第 1～7 條（與 `五人團隊分工與Spec開發建議書.md` 的檢查清單一致）。
4. FastAPI 中一段 Python 能成功用 **boto3 / Strands** 呼叫 Bedrock。
5. IAM role 具備：Bedrock InvokeModel、KB Retrieve、S3 讀取、（選配）DynamoDB 寫入權限。
6. AWS Credential 由個人環境提供，**不寫入程式碼或 Git**。

`.env.example` 的欄位定義以 `五人團隊分工與Spec開發建議書.md` 第七章為**單一來源**，本文件不另行定義，避免兩份清單分歧。與 AWS 相關的欄位為 `AWS_REGION`、`BEDROCK_MODEL_ID`、`BEDROCK_KNOWLEDGE_BASE_ID`、`S3_DATA_BUCKET`、`DECISION_LOG_TABLE`、`USE_BEDROCK`。

---

## 七、成本與風險快速備註

| 項目 | 備註 |
|---|---|
| S3 Vectors | 少量 SOP 向量成本極低；無常駐節點費用；`us-west-2` 已支援 |
| Bedrock FM | 依 token 計費；Demo 情境固定，用量可控 |
| Knowledge Bases | 檢索按次計費，Demo 量小 |
| DynamoDB | 按需計費，Demo 量小近乎免費 |
| AgentCore Runtime | 有部署/執行成本，僅 Day3 加分再用 |
| 風險：模型未開通（新手最常見） | Day 0 最先做 Model access，錯誤訊息為 `AccessDeniedException` |
| 風險：KB 查不到內容 | 上傳 S3 後回 KB 頁面按 Sync，等狀態變 Ready |
| 風險：region 無 S3 Vectors | 已非主要風險（`us-west-2` 支援）；仍可退回 OpenSearch Serverless |
| 風險：AWS 完全連不上 | `USE_BEDROCK=false` 走本機保底模式（見 0.6），Demo 仍可完整展示 |
| 風險：AgentCore 部署卡住 | 回到 FastAPI 直接 boto3/Strands 呼叫 Bedrock |
| 風險：LLM 竄改數字/條款 | 數字/條款 ID/路線由 Python 注入，並加 Guardrails |
