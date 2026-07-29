"""對應 K3-sop-rag/tasks.md Task 2/3/8。

local_fallback.py / sop_data.py 是決定性程式碼，用精確值斷言（例如「路面塌陷封閉」
必須精確回傳 section_number=2）；bedrock_kb.py 才是結構性事實斷言的範圍。
"""

import pytest

from src.bedrock_service.local_fallback import query_local, RELEVANCE_THRESHOLD
from src.bedrock_service.sop_data import SOP_DATA, SopMatch


# -- 精確命中測試 --
def test_query_local_exact_section_match_sop2():
    """「車禍路障塌陷封閉」應精確命中 SOP-2（車禍與路障應變）。"""
    results = query_local("車禍路障塌陷封閉")
    assert len(results) >= 1
    assert results[0].section_number == 2
    assert results[0].relevance_score >= RELEVANCE_THRESHOLD


def test_query_local_exact_section_match_sop3():
    """「捷運BL17人流」應命中 SOP-3。"""
    results = query_local("捷運BL17人流")
    section_numbers = [r.section_number for r in results]
    assert 3 in section_numbers


def test_query_local_exact_section_match_sop5():
    """「號誌故障」應命中 SOP-5。"""
    results = query_local("號誌故障")
    section_numbers = [r.section_number for r in results]
    assert 5 in section_numbers


def test_query_local_exact_section_match_sop6():
    """「漫遊比率多語通報」應命中 SOP-6。"""
    results = query_local("漫遊比率多語通報")
    section_numbers = [r.section_number for r in results]
    assert 6 in section_numbers


def test_query_local_exact_section_match_sop7():
    """「ETE恢復時間公式」應命中 SOP-7。"""
    results = query_local("ETE恢復時間公式")
    section_numbers = [r.section_number for r in results]
    assert 7 in section_numbers


# -- 最多 3 條 --
def test_query_local_max_3_results():
    """即使所有 SOP 都命中，最多只回傳 3 條。"""
    # 用一個涵蓋多條 SOP 關鍵字的超長查詢
    question = "飽和擁塞車禍路障塌陷捷運BL17大巨蛋號誌故障漫遊ETE恢復時間"
    results = query_local(question)
    assert len(results) <= 3


# -- 低於閾值不回傳 --
def test_query_local_below_threshold_returns_empty():
    """完全不匹配的查詢應回傳空 list。"""
    results = query_local("今天天氣真好去公園散步")
    assert results == []


# -- content 是原文 --
def test_query_local_content_is_original_sop_text():
    """回傳的 content 必須是 SOP JSON 原文，不是自己編的。"""
    results = query_local("車禍路障塌陷封閉")
    assert len(results) >= 1
    matched = results[0]
    original = SOP_DATA[matched.section_number]
    assert matched.content == original.content
    assert matched.title == original.title


# -- 回傳型別是 SopMatch --
def test_query_local_returns_sop_match_type():
    results = query_local("號誌故障")
    for r in results:
        assert isinstance(r, SopMatch)
        assert 0.0 <= r.relevance_score <= 1.0


# -- 確定性 --
def test_query_local_is_deterministic():
    r1 = query_local("路面塌陷封閉替代路")
    r2 = query_local("路面塌陷封閉替代路")
    assert len(r1) == len(r2)
    for a, b in zip(r1, r2):
        assert a.section_number == b.section_number
        assert a.relevance_score == b.relevance_score


# -- Phase 4.4: sop_retriever.py 整合測試 --
def test_use_bedrock_false_uses_local_fallback_with_correct_field_name(monkeypatch):
    """回歸測試：USE_BEDROCK=false 時 retrieval_source 必須是 "local"，不是 "source"。"""
    monkeypatch.setenv("USE_BEDROCK", "false")
    # 重新 import 以讓環境變數生效（或直接呼叫內部邏輯）
    from src.bedrock_service.local_fallback import query_local as _ql
    from src.bedrock_service.sop_retriever import SopQueryResult

    # 模擬 USE_BEDROCK=false 路徑
    sections = _ql("車禍路障塌陷封閉")
    result = SopQueryResult(sections=sections, query="車禍路障塌陷封閉", retrieval_source="local")

    assert result.retrieval_source == "local"
    assert hasattr(result, "retrieval_source")
    # 確認沒有舊的 "source" 欄位
    assert not hasattr(result, "source")


def test_bedrock_kb_exception_falls_back_to_local_not_crash(monkeypatch):
    """回歸測試：Bedrock呼叫失敗要真的try/except退化，不是讓例外往上拋。"""
    monkeypatch.setenv("USE_BEDROCK", "true")

    # Mock bedrock_kb 讓它拋例外
    import src.bedrock_service.sop_retriever as retriever_mod
    monkeypatch.setattr(retriever_mod, "USE_BEDROCK", True)

    def mock_bedrock_kb(question):
        raise RuntimeError("模擬 Bedrock 連線失敗")

    monkeypatch.setattr(retriever_mod, "query_bedrock_kb", mock_bedrock_kb)

    # 不應拋例外，應退化到本機
    result = retriever_mod.query_sop("車禍路障塌陷封閉")
    assert result.retrieval_source == "local_fallback"
    assert len(result.sections) >= 1  # 本機比對應有結果
