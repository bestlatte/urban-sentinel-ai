"""全專案共用的 Bedrock 呼叫層。

為什麼要有這個檔案
------------------
在此之前專案裡有三套各自獨立的 LLM 呼叫方式，行為互相對不上：

| 呼叫端 | 方式 | USE_BEDROCK 檢查 | 逾時 |
|---|---|---|---|
| `agent/a2_orchestrator_agent.py` | Strands Agent | 有（call-time） | 有（8s） |
| `agent/whatif_agent.py` | Strands Agent | **無** | **無** |
| `reporting.py` / `decision_trace.py` | boto3 converse | 有（call-time） | **無** |
| `bedrock_service/sop_retriever.py` | boto3 retrieve | 有（**import-time**） | **無** |

後果是保底模式（`00-tech-stack.md` §6）只對其中一半生效，而沒有逾時的路徑在
Demo 現場網路不穩時會整條掛住。這個模組把「讀哪個 region / 哪個 model、要不要
真的打 Bedrock、等多久放棄」收斂成單一決策點，四個呼叫端全部改走這裡。

刻意不做的事
------------
不包裝 prompt、不解析回應、不決定降級後要回什麼——那些是各呼叫端的職責。
本模組只負責「把字送出去、把字拿回來，或在時限內放棄」。
"""

from __future__ import annotations

import contextvars
import logging
import os
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout
from typing import Any, Callable, TypeVar

from src.models import DEFAULT_BEDROCK_MODEL_ID, DEFAULT_REPORT_MODEL_ID

logger = logging.getLogger(__name__)

T = TypeVar("T")


CONVERSE_TIMEOUT_S = 30.0
"""boto3 converse 的逾時。建議書（C1-C3）是全專案最長的一次生成，實測約 20 秒，
留 30 秒緩衝。"""

AGENT_TIMEOUT_S = 60.0
"""W1 對話 Agent 的逾時。

[2026-08-01 實測] 一次 W1 呼叫（`query_sop` ×3 + `simulate_scenario` ×1，
共 4 輪 tool-call 往返）耗時 **31.6 秒**。先前設 25 秒會讓正常的對話被誤判成
逾時而降級——逾時值必須大於實測值，不然護欄擋掉的是正常流量而不是異常流量。
60 秒留了將近一倍餘裕。

使用者互動情境下寧可等，也不要拿到一份降級的答案：W1 降級只剩本機 SOP 關鍵字
比對，沒有路線也沒有 ETE。

註：A2 規劃器另有 `PLANNER_TIMEOUT_S = 8.0`（SPEC-O2 §4.3 明訂的逾時預算），
不套用這個值，規格數字優先。
"""

ADVISORY_TIMEOUT_S = 15.0
"""決策週期內 `LiveGateway.run_agent()` 呼叫 W1 取 `BedrockAdvisory` 的逾時。

刻意比 `AGENT_TIMEOUT_S` 短很多，因為這是**兩個完全不同的情境**：

- W1 對話：使用者盯著畫面等答案，答案本身就是產品。等 60 秒可接受。
- 決策週期內的 advisory：七階段之一，後面還有報告生成要跑，而且拖的是整個
  事件應變的時間。

實測這個呼叫佔掉決策週期約一半的耗時（雲端整輪 67 秒）。超時就用 stub 值，
週期繼續走——`degraded` 會記 `ADVISORY_DEGRADED`，不會靜默。
"""


# ---------------------------------------------------------------------------
# 設定讀取（一律 call-time，不得在 import 時固化）
# ---------------------------------------------------------------------------


def bedrock_enabled() -> bool:
    """保底模式旗標（`00-tech-stack.md` §6）。

    **必須每次呼叫時讀**，不得存成模組層級常數。`sop_retriever.py` 原本寫成
    import-time 常數，造成兩個實際問題：行程啟動後改環境變數無效，以及測試用
    `monkeypatch.setenv` 完全 patch 不到（得改 patch 模組屬性才會動）。
    """
    return os.getenv("USE_BEDROCK", "true").lower() == "true"


def get_region() -> str:
    """優先 `AWS_REGION`，再退 `AWS_DEFAULT_REGION`，最後預設 us-west-2。

    兩個變數都收是因為 `.env` 實務上兩種寫法都有人用（boto3 自己也兩個都認），
    只認一個會出現「明明設了 region 卻連到別區」這種很難查的狀況。
    """
    return (
        os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or "us-west-2"
    )


def get_model_id() -> str:
    """留空或未設定時用 `src/models.py` 的 `DEFAULT_BEDROCK_MODEL_ID`。

    `os.environ.get(k, default)` 對「設了但值是空字串」會回空字串（`.env` 裡
    `BEDROCK_MODEL_ID=` 就是這種情況），所以這裡用 `or` 而不是 default 參數。
    """
    return os.environ.get("BEDROCK_MODEL_ID") or DEFAULT_BEDROCK_MODEL_ID


def get_report_model_id() -> str:
    """C1-C4 建議書／簡訊專用的模型（預設 Haiku，理由見 `DEFAULT_REPORT_MODEL_ID`）。

    刻意**不**回退到 `BEDROCK_MODEL_ID`：那個變數是給需要推理的 A2／W1 用的，
    若讓它一併覆蓋 C1-C4，「把建議書換成快模型」這個決定就會被一個看起來無關的
    設定悄悄推翻。要改就顯式設 `BEDROCK_REPORT_MODEL_ID`。
    """
    return os.environ.get("BEDROCK_REPORT_MODEL_ID") or DEFAULT_REPORT_MODEL_ID


def get_knowledge_base_id() -> str:
    """留空代表沒有 KB，呼叫端應直接走本機保底，不要送出請求。

    留空時若照送，botocore 會在參數驗證階段就拋
    `Invalid length for parameter knowledgeBaseId, value: 0, valid min length: 10`
    ——這個例外雖然會被上層接住降級，但每次查詢都白繞一圈，且日誌被無意義的
    stack trace 洗版，掩蓋真正的錯誤。
    """
    return os.environ.get("BEDROCK_KNOWLEDGE_BASE_ID", "").strip()


# ---------------------------------------------------------------------------
# 逾時包裝
# ---------------------------------------------------------------------------


def run_with_timeout(fn: Callable[[], T], timeout_s: float, label: str = "LLM") -> T:
    """在工作執行緒跑 `fn`，超過 `timeout_s` 拋 `TimeoutError`。

    逾時後該執行緒仍會跑完（Python 沒有安全的中斷機制），但結果被丟棄。這對
    本專案是可接受的：所有 LLM 呼叫都是唯讀的文字生成，跑完不會產生副作用。

    注意 `ThreadPoolExecutor` 的 context manager 在 `__exit__` 會 join 工作
    執行緒，若直接 `with` 包住會把逾時的效果抵銷掉（等於還是等它跑完）。
    所以這裡手動建立、逾時時以 `shutdown(wait=False)` 放生。

    **ContextVar 必須手動複製過去**：`ThreadPoolExecutor.submit()` 不會帶
    context，而 `orchestrator._current_trace_ctx`（記錄使用者正在看哪條決策
    週期）是 ContextVar。少了這一步，`agent/tools.py::simulate_scenario` 在
    工作執行緒裡讀到的 trace_id 永遠是 None，What-if 會退化成「不依賴特定事件
    的模擬」——路線與 ETE 全部算不出來，而且完全沒有錯誤訊息。
    """
    ctx = contextvars.copy_context()

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        future = pool.submit(ctx.run, fn)
        try:
            return future.result(timeout=timeout_s)
        except FuturesTimeout:
            future.cancel()
            raise TimeoutError(f"{label} 逾時（>{timeout_s:g}s）") from None
    finally:
        # wait=False：不等背景執行緒收工，逾時才有意義
        pool.shutdown(wait=False)


# ---------------------------------------------------------------------------
# boto3 Converse（C1-C4 建議書、M4B 解釋鏈、W1 情境建議書共用）
# ---------------------------------------------------------------------------


def invoke_converse(
    system_prompt: str,
    user_message: str,
    *,
    max_tokens: int = 2000,
    temperature: float = 0.3,
    timeout_s: float = CONVERSE_TIMEOUT_S,
    model_id: str | None = None,
) -> str:
    """呼叫 Bedrock Converse API 生成文字，回傳純文字。

    失敗（含逾時）一律拋例外，由呼叫端決定降級行為——本模組不替呼叫端決定
    「失敗時要回什麼」，那是各自的業務判斷。

    Args:
        model_id: 覆寫模型。預設 `get_model_id()`；C1-C4 會傳
            `get_report_model_id()`（Haiku）。
    """
    import time

    import boto3
    from botocore.config import Config

    from src import bedrock_status

    region = get_region()
    model_id = model_id or get_model_id()

    # botocore 自己的 read_timeout 是第一道防線（比 thread 逾時更省資源），
    # run_with_timeout 是第二道——涵蓋 boto3 重試、連線建立等 read_timeout
    # 管不到的階段。兩道都要，只有其中一道都擋不住實際發生過的卡死情境。
    config = Config(
        read_timeout=int(timeout_s),
        connect_timeout=10,
        retries={"max_attempts": 2, "mode": "standard"},
    )
    client = boto3.client("bedrock-runtime", region_name=region, config=config)

    def _call() -> str:
        response = client.converse(
            modelId=model_id,
            messages=[{"role": "user", "content": [{"text": user_message}]}],
            system=[{"text": system_prompt}],
            inferenceConfig={"maxTokens": max_tokens, "temperature": temperature},
        )
        return response["output"]["message"]["content"][0]["text"]

    # [2026-08-01] 每次真實呼叫的成敗都回報給 `bedrock_status`。
    #
    # 為什麼把探針放在這裡而不是另開背景輪詢：真實流量本來就是最準確的探針，
    # 而且它涵蓋的是**實際用到的那個模型**——C1-C4 走 Haiku、A2/W1 走 Sonnet，
    # 輪詢只驗一個的話，另一個下架了照樣不會發現。
    #
    # 失敗一律往上拋（維持原本的契約：呼叫端自己決定降級行為），這裡只是順路
    # 記一筆，不改變任何控制流。
    started = time.perf_counter()
    try:
        result = run_with_timeout(_call, timeout_s, label=f"Converse({model_id})")
    except Exception as e:
        bedrock_status.record_failure(e)
        raise
    bedrock_status.record_success(model_id, int((time.perf_counter() - started) * 1000))
    return result


# ---------------------------------------------------------------------------
# Strands 模型實例（A2 規劃器與 W1 對話 Agent 共用）
# ---------------------------------------------------------------------------


_MODEL_CACHE: dict[str, Any] = {}


def get_strands_model():
    """回傳快取的 Strands `BedrockModel`。

    快取的是 **model**（內含 boto3 client）而不是 **Agent**。這個區分很重要：

    - `BedrockModel` 是無狀態的，共用安全，而且建立時要開 boto3 client，
      每次請求重建會多付幾百毫秒。
    - `Agent` **有狀態**——`agent.messages` 會累積對話歷史。之前 W1 快取的是
      全域 Agent 實例，等於所有使用者、所有 session 共用同一份對話歷史：既會
      跨 session 洩漏內容，也會讓歷史無限增長直到爆 context window。W1 的對話
      歷史本來就由 W2 `session_manager` 管理並注入 prompt，Agent 自己再記一份
      純屬多餘。

    所以：model 快取、Agent 每次新建。
    """
    key = f"{get_region()}::{get_model_id()}"
    if key not in _MODEL_CACHE:
        from botocore.config import Config
        from strands.models import BedrockModel

        _MODEL_CACHE[key] = BedrockModel(
            model_id=get_model_id(),
            region_name=get_region(),
            boto_client_config=Config(
                read_timeout=int(AGENT_TIMEOUT_S),
                connect_timeout=10,
                retries={"max_attempts": 2, "mode": "standard"},
            ),
        )
    return _MODEL_CACHE[key]


def reset_model_cache() -> None:
    """測試輔助：清掉快取，讓下次呼叫依當前環境變數重建。"""
    _MODEL_CACHE.clear()
