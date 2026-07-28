"""對應 K3-sop-rag/tasks.md Task 2/3/8。

local_fallback.py / sop_data.py 是決定性程式碼，用精確值斷言（例如「路面塌陷封閉」
必須精確回傳 section_number=2）；bedrock_kb.py 才是結構性事實斷言的範圍。
"""

import pytest


def test_query_local_exact_section_match():
    pytest.skip("TODO(Kiro): 依 K3-sop-rag/tasks.md Task 2 完成標準實作")


def test_use_bedrock_false_uses_local_fallback_with_correct_field_name():
    """回歸測試：欄位名必須是 retrieval_source，不是 source（本次審查修正過）。"""
    pytest.skip("TODO(Kiro): 依 K3-sop-rag/design.md 第五節實作")


def test_bedrock_kb_exception_falls_back_to_local_not_crash():
    """回歸測試：Bedrock呼叫失敗要真的try/except退化，不是讓例外往上拋。"""
    pytest.skip("TODO(Kiro): 依 K3-sop-rag/design.md 第五節實作")
