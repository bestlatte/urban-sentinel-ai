"""對應 m4-decision-reporting/requirements.md 第四節驗收測試(#1-8)。"""

import pytest


def test_calculate_ete_three_golden_events():
    pytest.skip("TODO(Kiro): 依 m4-decision-reporting/requirements.md 測試 #1/#2 實作")


def test_generate_report_notification_is_single_object_not_list():
    """回歸測試：generate_report() 第二回傳值是單一物件 {zh,en?,ja?,ko?}，
    不是 list[Notification]（本次審查修正過的欄位形狀）。"""
    pytest.skip("TODO(Kiro): 依 m4-decision-reporting/requirements.md §3.5 實作")


def test_llm_does_not_alter_fact_fields():
    """對同一組輸入呼叫兩次，用詞可以不同，但路段名/ETE數值/SOP編號必須逐字相同。"""
    pytest.skip("TODO(Kiro): 依 m4-decision-reporting/requirements.md 測試 #8 實作")
