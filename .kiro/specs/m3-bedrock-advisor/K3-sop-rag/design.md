# K3 — SOP RAG 檢索服務 | Design

> 前置文件：`specs/K3-sop-rag/requirements.md`
> 本文件定義 K3 的技術實作方式，供開發與整合參考。

> **[2026-07-28 總架構師補註]** 核對出兩處需要修正：
> 1. `SOPQueryResult` 的欄位原寫 `source`，且註解只列「`"bedrock"` 或 `"local"`」兩種值。但 `00-tech-stack.md` §6（保底模式硬性要求）已經明訂欄位名是 `retrieval_source`、失敗退化時的值是 `"local_fallback"`——這是全專案共用的欄位名，其他模組（`orchestrator.py`／Envelope `warnings`）會用這個名字檢查是否處於保底模式。若 K3 自己叫 `source`，其他模組讀不到會恆為 `None`，保底狀態就沒辦法正確標記。以下已全部改為 `retrieval_source`，且三種值（`bedrock`／`local`／`local_fallback`）都列出來。
> 2. 第五節的模式切換程式碼沒有 `try/except`，但第八節錯誤處理表格說「Bedrock API 呼叫失敗時自動退化到本機模式」——照原程式碼寫法，`_query_bedrock_kb()` 拋出例外會讓整個 `query_sop()` 直接崩潰，並不會真的退化。已補上例外處理，讓第八節描述的行為真正被實作出來。
>
> 另外，第十節檔案結構寫 `src/rag/`，但 `00-tech-stack.md` §3 固定結構裡 K3 對應的檔案是單一的 `src/bedrock_service.py`（`01-module-boundaries.md` 模組3的所有權範圍）。建議把 `src/rag/` 底下這幾個檔案當作 `bedrock_service.py` 內部的組織方式（同一個檔案裡分段落，或改成 `src/bedrock_service/` 子套件取代單一檔案，兩種都可以），但對外只透過 `bedrock_service` 這個名稱曝露，不要在 `src/` 底下另外長出一個跟模組所有權表對不起來的 `rag/` 頂層目錄。

---

## 一、架構總覽

```
呼叫者 (A2 / W1)
       │
       │  query_sop(question: str)
       ▼
┌─────────────────────────────┐
│         K3 模組              │
│                             │
│  ┌─── USE_BEDROCK=true ──┐  │
│  │  Bedrock KB Retrieve  │  │
│  │  API 呼叫             │  │
│  └───────────────────────┘  │
│                             │
│  ┌─── USE_BEDROCK=false ─┐  │
│  │  本機關鍵字比對        │  │
│  │  (fallback)           │  │
│  └───────────────────────┘  │
│                             │
│  統一回傳格式               │
└─────────────────────────────┘
       │
       ▼
回傳 SOPQueryResult
```

K3 對外只暴露一個 function，內部根據環境變數切換雲端/本機模式。呼叫者不需要知道底層用的是 Bedrock 還是關鍵字比對。

---

## 二、對外介面

### Function Signature

```python
def query_sop(question: str) -> SOPQueryResult:
    """
    查詢 SOP 條款。

    Args:
        question: 自然語言問題（中文）

    Returns:
        SOPQueryResult 包含最相關的 SOP 條款列表
    """
```

### 回傳資料結構

```python
from dataclasses import dataclass

@dataclass
class SOPSection:
    section_number: int       # 1~7
    title: str                # 條款標題，例如「車禍與路障應變」
    content: str              # 條款完整原文（不改寫）
    relevance_score: float    # 0.0 ~ 1.0

@dataclass
class SOPQueryResult:
    sections: list[SOPSection]  # 最多 3 條，依 score 降序
    query: str                  # 原始查詢（方便除錯/稽核）
    retrieval_source: str       # "bedrock" / "local" / "local_fallback"（欄位名對齊 00-tech-stack.md §6）
```

### 行為規則

- `sections` 最多回傳 3 條。
- 若所有候選 score < 閾值（`RELEVANCE_THRESHOLD`，預設 0.3），回傳空 `sections: []`。
- `content` 必須是 `emergency_traffic_sop.json` 中的原文完整複製。

---

## 三、雲端模式（Bedrock KB）

### 前置設定（一次性）

1. 從 `data/emergency_traffic_sop.json` 衍生 7 個文字檔：
   - 檔名格式：`SOP-{section_number}-{title}.txt`
   - 內容格式：
     ```
     SOP 第 {section_number} 條：{title}

     {content}
     ```
2. 上傳至 S3 bucket（`s3://{S3_DATA_BUCKET}/sop-index/`）。
3. 建立 Bedrock Knowledge Base，向量儲存選 S3 Vectors。
4. 觸發 KB Sync，確認狀態為 Ready。

### 查詢流程

```python
import boto3

def _query_bedrock_kb(question: str) -> list[SOPSection]:
    client = boto3.client("bedrock-agent-runtime", region_name=AWS_REGION)
    
    response = client.retrieve(
        knowledgeBaseId=BEDROCK_KNOWLEDGE_BASE_ID,
        retrievalQuery={"text": question},
        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": 3
            }
        }
    )
    
    results = []
    for item in response["retrievalResults"]:
        score = item["score"]
        if score < RELEVANCE_THRESHOLD:
            continue
        
        # 從回傳的 text 中解析 section_number
        # 或從 metadata 取得（視 KB 設定）
        section = _parse_section_from_kb_result(item)
        if section:
            results.append(section)
    
    return results
```

### 重要細節

- KB 回傳的 text 可能被 chunking 切斷，因此**不直接使用 KB 回傳的 text 作為 content**。
- 正確做法：用 KB 回傳結果辨識出 `section_number`，然後從本機的 `emergency_traffic_sop.json` 取出完整原文。
- 這確保 `content` 永遠是完整的、不被截斷的 SOP 原文。

```python
def _parse_section_from_kb_result(item) -> SOPSection | None:
    """從 KB 結果辨識 section_number，再從本機 JSON 取完整原文"""
    text = item["content"]["text"]
    score = item["score"]
    
    # 從文字開頭的格式辨識 section_number
    # 格式："SOP 第 N 條：..."
    section_number = _extract_section_number(text)
    if section_number is None:
        return None
    
    # 從本機 JSON 取完整原文
    full_section = SOP_DATA[section_number]  # 預載入記憶體的 dict
    
    return SOPSection(
        section_number=full_section["section_number"],
        title=full_section["title"],
        content=full_section["content"],
        relevance_score=score
    )
```

---

## 四、本機保底模式（關鍵字比對）

### 策略

SOP 只有 7 條，每條有明確的觸發關鍵字。用簡單的比對就能達到「堪用」的效果。

### 關鍵字映射表

```python
KEYWORD_MAP = {
    1: ["飽和", "擁塞", "A級", "B級", "紅燈", "黃燈", "級別", "Saturation"],
    2: ["車禍", "路障", "塌陷", "封閉", "Closed", "Blocked", "替代路", "疏散", "上游", "下游"],
    3: ["捷運", "BL17", "接駁", "過站不停", "人流", "Growth_Rate", "User_Count"],
    4: ["大巨蛋", "散場", "DOME", "峰值"],
    5: ["號誌", "故障", "Power_Failure", "人工指揮"],
    6: ["漫遊", "Roaming", "多語", "簡訊", "通報"],
    7: ["ETE", "恢復時間", "base_clearance", "congestion_penalty", "公式"],
}
```

### 比對邏輯

```python
def _query_local(question: str) -> list[SOPSection]:
    scores = {}
    
    for section_number, keywords in KEYWORD_MAP.items():
        hit_count = sum(1 for kw in keywords if kw.lower() in question.lower())
        if hit_count > 0:
            # 簡易分數：命中數 / 該 section 的關鍵字總數
            scores[section_number] = hit_count / len(keywords)
    
    # 依分數排序，取前 3
    sorted_sections = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]
    
    results = []
    for section_number, score in sorted_sections:
        if score < RELEVANCE_THRESHOLD:
            continue
        full_section = SOP_DATA[section_number]
        results.append(SOPSection(
            section_number=full_section["section_number"],
            title=full_section["title"],
            content=full_section["content"],
            relevance_score=round(score, 3)
        ))
    
    return results
```

### 本機模式的限制（可接受）

- 無法處理語義相似但用詞不同的查詢（例如「人太多了怎麼辦」不會命中第 3 條）
- 但對 Demo 場景夠用，因為評審通常會用接近 SOP 術語的問法

---

## 五、模式切換邏輯

```python
import os
import logging

USE_BEDROCK = os.getenv("USE_BEDROCK", "true").lower() == "true"

def query_sop(question: str) -> SOPQueryResult:
    if USE_BEDROCK:
        try:
            sections = _query_bedrock_kb(question)
            retrieval_source = "bedrock"
        except Exception:
            logging.exception("Bedrock KB 呼叫失敗，退化為本機關鍵字比對")
            sections = _query_local(question)
            retrieval_source = "local_fallback"
    else:
        sections = _query_local(question)
        retrieval_source = "local"
    
    return SOPQueryResult(
        sections=sections,
        query=question,
        retrieval_source=retrieval_source
    )
```

---

## 六、SOP 資料預載

系統啟動時，將 `emergency_traffic_sop.json` 載入記憶體：

```python
import json

def _load_sop_data() -> dict[int, dict]:
    with open("data/emergency_traffic_sop.json", "r", encoding="utf-8") as f:
        raw = json.load(f)
    
    return {
        section["section_number"]: section
        for section in raw["sections"]
    }

SOP_DATA = _load_sop_data()  # 啟動時載入，全域使用
```

這份資料用於：
- 雲端模式：KB 回傳 section_number 後，從這裡取完整原文
- 本機模式：直接從這裡比對和回傳

---

## 七、設定值

| 環境變數 | 預設值 | 說明 |
|---------|--------|------|
| `USE_BEDROCK` | `"true"` | 是否使用 Bedrock KB |
| `AWS_REGION` | `"us-west-2"` | AWS 區域 |
| `BEDROCK_KNOWLEDGE_BASE_ID` | 無預設（雲端模式必填） | KB 的 ID |

| 常數 | 值 | 說明 |
|------|---|------|
| `RELEVANCE_THRESHOLD` | `0.3` | 低於此分數不回傳 |
| `MAX_RESULTS` | `3` | 最多回傳幾條 |

---

## 八、錯誤處理

| 情境 | 處理方式 |
|------|---------|
| Bedrock API 呼叫失敗（網路錯誤、timeout） | 自動退化到本機模式，`retrieval_source` 標為 `"local_fallback"`（見第五節 `try/except`） |
| KB 回傳空結果 | 正常回傳 `sections: []` |
| SOP JSON 檔案讀取失敗 | 啟動時直接報錯終止（這是不可恢復的錯誤） |
| `section_number` 無法從 KB 結果解析 | 跳過該筆結果，不回傳 |

---

## 九、Strands Agent 整合（供 A2 / W1 呼叫）

K3 同時註冊為 Strands Agent 的 `@tool`，讓 A2 和 W1 可以自然呼叫：

```python
from strands import tool

@tool
def query_sop(question: str) -> dict:
    """查詢 SOP 條款。輸入自然語言問題，回傳最相關的 SOP 條款原文與條款編號。"""
    result = _query_sop_internal(question)
    return {
        "sections": [
            {
                "section_number": s.section_number,
                "title": s.title,
                "content": s.content,
                "relevance_score": s.relevance_score
            }
            for s in result.sections
        ],
        "retrieval_source": result.retrieval_source
    }
```

---

## 十、檔案結構（預期）

```
src/
└── bedrock_service/           # 取代固定結構裡的單一 bedrock_service.py，內部拆檔但對外仍是同一個模組名稱
    ├── __init__.py             # 對外曝露 query_sop()（供 agent.py 的 @tool 註冊）
    ├── sop_retriever.py        # query_sop() 主邏輯 + 模式切換
    ├── bedrock_kb.py           # Bedrock KB 呼叫封裝
    ├── local_fallback.py       # 本機關鍵字比對
    └── sop_data.py             # SOP JSON 預載 + 資料結構定義
```
