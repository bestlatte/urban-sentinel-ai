"""Bedrock Knowledge Bases 呼叫封裝（雲端路徑）。這是唯一真的呼叫 AWS 的部分，
適用 `.kiro/steering/03-testing-and-ai-collaboration.md` §2.2 的結構性事實斷言，
不是 §2.1 的精確值斷言（LLM/雲端服務輸出不可 100% 決定性重現）。

參考 spec：`.kiro/specs/m3-bedrock-advisor/K3-sop-rag/design.md` 第三節。
"""

from __future__ import annotations

from src.bedrock_service.sop_data import SopMatch


def query_bedrock_kb(question: str) -> list[SopMatch]:
    """呼叫 Bedrock KB Retrieve API，並用回傳結果辨識 section_number 後，
    從本機 SOP_DATA 取完整原文——KB 回傳的 text 可能被 chunking 切斷，
    不得直接拿來當 content（design.md 第三節「重要細節」）。

    TODO(Kiro): boto3 bedrock-agent-runtime client，numberOfResults=3，
    score < RELEVANCE_THRESHOLD 的過濾掉。
    """
    raise NotImplementedError("見 K3-sop-rag/design.md 第三節")
