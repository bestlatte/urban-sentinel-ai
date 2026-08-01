"""Bedrock Knowledge Bases 呼叫封裝（雲端路徑）。這是唯一真的呼叫 AWS 的部分，
適用 `.kiro/steering/03-testing-and-ai-collaboration.md` §2.2 的結構性事實斷言，
不是 §2.1 的精確值斷言（LLM/雲端服務輸出不可 100% 決定性重現）。

參考 spec：`.kiro/specs/m3-bedrock-advisor/K3-sop-rag/design.md` 第三節。
"""

from __future__ import annotations

import re

import boto3

from src.bedrock_service.sop_data import SOP_DATA, SopMatch
from src.llm import get_knowledge_base_id, get_region

RELEVANCE_THRESHOLD = 0.3
MAX_RESULTS = 3


def _extract_section_number(text: str) -> int | None:
    """從 KB 回傳的 text 片段中辨識 section_number。

    預期格式（由 scripts/generate_sop_index_files.py 產生）：
    "SOP 第 N 條：..." 或檔名格式 "SOP-N-..."
    """
    # 嘗試格式 "SOP 第 N 條"
    match = re.search(r"SOP\s*第\s*(\d+)\s*條", text)
    if match:
        return int(match.group(1))

    # 嘗試格式 "SOP-N"
    match = re.search(r"SOP-(\d+)", text)
    if match:
        return int(match.group(1))

    # 嘗試純內容比對（最後手段）
    for section_num, section in SOP_DATA.items():
        if section.title in text:
            return section_num

    return None


def query_bedrock_kb(question: str) -> list[SopMatch]:
    """呼叫 Bedrock KB Retrieve API，並用回傳結果辨識 section_number 後，
    從本機 SOP_DATA 取完整原文——KB 回傳的 text 可能被 chunking 切斷，
    不得直接拿來當 content。

    [2026-08-01] region 與 KB ID 改成呼叫時才讀（`src/llm.py`），不再是
    import-time 模組常數——原本 import 之後就固化，`.env` 載入時機只要晚一步
    就會連到錯的 region 或用到空的 KB ID，而且完全沒有徵兆。
    """
    client = boto3.client("bedrock-agent-runtime", region_name=get_region())

    response = client.retrieve(
        knowledgeBaseId=get_knowledge_base_id(),
        retrievalQuery={"text": question},
        retrievalConfiguration={
            "vectorSearchConfiguration": {
                "numberOfResults": MAX_RESULTS,
            }
        },
    )

    results: list[SopMatch] = []
    seen_sections: set[int] = set()

    for item in response.get("retrievalResults", []):
        score = item.get("score", 0.0)
        if score < RELEVANCE_THRESHOLD:
            continue

        text = item.get("content", {}).get("text", "")
        section_number = _extract_section_number(text)
        if section_number is None or section_number not in SOP_DATA:
            continue
        if section_number in seen_sections:
            continue
        seen_sections.add(section_number)

        full_section = SOP_DATA[section_number]
        results.append(SopMatch(
            section_number=full_section.section_number,
            title=full_section.title,
            content=full_section.content,
            relevance_score=score,
        ))

    return results
