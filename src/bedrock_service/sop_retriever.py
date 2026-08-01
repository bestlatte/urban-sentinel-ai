"""query_sop() 主邏輯 + USE_BEDROCK 模式切換。

參考 spec：`.kiro/specs/m3-bedrock-advisor/K3-sop-rag/design.md` 第五節（已修正版：
含 try/except 讓保底行為真的生效，欄位名 retrieval_source 不是 source）。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from src.bedrock_service.bedrock_kb import query_bedrock_kb
from src.bedrock_service.local_fallback import query_local
from src.bedrock_service.sop_data import SopMatch
from src.llm import bedrock_enabled, get_knowledge_base_id

logger = logging.getLogger(__name__)


@dataclass
class SopQueryResult:
    sections: list[SopMatch]
    query: str
    retrieval_source: str
    """"bedrock" / "local" / "local_fallback"；欄位名對齊 00-tech-stack.md §6，
    其他模組靠這個名字判斷是否進入保底模式，不得改名。"""


def query_sop(question: str) -> SopQueryResult:
    """對外唯一入口，內部依 USE_BEDROCK 與呼叫成功與否切換雲端/本機模式。

    Bedrock 呼叫失敗時 (except Exception) 真的 fallback 到 query_local()，
    retrieval_source 設為 "local_fallback"，不是讓例外往上拋。

    [2026-08-01 修正兩點]
    1. `USE_BEDROCK` 改成呼叫時才讀（`llm.bedrock_enabled()`），不再是 import-time
       模組常數——原本的寫法讓行程啟動後改環境變數無效，測試也 patch 不到。
    2. 沒設 `BEDROCK_KNOWLEDGE_BASE_ID` 時直接走本機，不送出注定失敗的請求。
       原本會讓 botocore 在參數驗證階段拋
       `Invalid length for parameter knowledgeBaseId, value: 0`，
       雖然有被接住降級，但每次查詢都白繞一圈並在日誌噴一整段 stack trace。
    """
    if bedrock_enabled():
        if not get_knowledge_base_id():
            logger.debug("未設定 BEDROCK_KNOWLEDGE_BASE_ID，直接使用本機關鍵字比對")
            sections = query_local(question)
            retrieval_source = "local_fallback"
        else:
            try:
                sections = query_bedrock_kb(question)
                retrieval_source = "bedrock"
            except Exception:
                logger.exception("Bedrock KB 呼叫失敗，退化為本機關鍵字比對")
                sections = query_local(question)
                retrieval_source = "local_fallback"
    else:
        sections = query_local(question)
        retrieval_source = "local"

    return SopQueryResult(
        sections=sections,
        query=question,
        retrieval_source=retrieval_source,
    )
