"""query_sop() 主邏輯 + USE_BEDROCK 模式切換。

參考 spec：`.kiro/specs/m3-bedrock-advisor/K3-sop-rag/design.md` 第五節（已修正版：
含 try/except 讓保底行為真的生效，欄位名 retrieval_source 不是 source）。
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass

from src.bedrock_service.bedrock_kb import query_bedrock_kb
from src.bedrock_service.local_fallback import query_local
from src.bedrock_service.sop_data import SopMatch

logger = logging.getLogger(__name__)

USE_BEDROCK = os.getenv("USE_BEDROCK", "true").lower() == "true"


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
    """
    if USE_BEDROCK:
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
