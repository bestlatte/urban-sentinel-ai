"""SOP JSON 預載入記憶體。純確定性、零 LLM——跟 local_fallback.py 一起適用
`.kiro/steering/03-testing-and-ai-collaboration.md` §2.1 的精確值斷言，
不是 §2.2 的 LLM 結構性斷言。

參考 spec：`.kiro/specs/m3-bedrock-advisor/K3-sop-rag/design.md` 第六節。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SopSection:
    section_number: int
    title: str
    content: str


@dataclass
class SopMatch:
    """一次查詢命中的結果。[2026-07-28總架構師補充：回應Kiro審查] 跟 `SopSection`
    分開——`SopSection` 是「儲存的原文」，沒有 relevance_score（分數是「這次查詢」
    跟「某章節」的關係，不是章節本身的屬性）。定義在這裡（而不是 `sop_retriever.py`）
    是為了讓 `local_fallback.py`/`bedrock_kb.py`/`sop_retriever.py` 都能 import
    同一個型別，不會互相循環依賴——這個檔案是套件裡最底層、不 import 同套件其他模組的
    唯一檔案。
    """

    section_number: int
    title: str
    content: str
    relevance_score: float


def load_sop_data() -> dict[int, SopSection]:
    """系統啟動時載入 data/emergency_traffic_sop.json，key 為 section_number。

    TODO(Kiro): 讀檔失敗時直接報錯終止（design.md §8：這是不可恢復的錯誤，
    不同於查詢失敗可以降級）。
    """
    raise NotImplementedError("見 K3-sop-rag/design.md 第六節")


SOP_DATA: dict[int, SopSection] = {}
"""啟動時由 load_sop_data() 填入，全域使用。"""
