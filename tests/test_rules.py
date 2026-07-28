"""對應 m1-data-ingestion/requirements.md 第六節，含測試 #6/#6b（SOP-1 全15路段分級
vs 城市應變觸發限定RD_TPE_001/002 兩段的區分——這是本次審查修過的真實bug，
兩條測試都要留著當回歸測試，不能只留一條）。
"""

import pytest


def test_sop1_ab_level_applies_to_all_15_segments():
    pytest.skip("TODO(Kiro): 依 m1-data-ingestion/requirements.md 測試 #6 實作")


def test_sop1_city_response_limited_to_two_segments():
    """回歸測試：SOP-1 城市應變觸發（長綠燈時制）只限 RD_TPE_001/002，
    不影響其他13路段的一般A/B分級——之前這裡曾經寫錯成分級本身也被限制。
    """
    pytest.skip("TODO(Kiro): 依 m1-data-ingestion/requirements.md 測試 #6b 實作")


def test_three_golden_events_ete_and_sop_hits():
    """ACC_001=90分/EVT_002=70分/EVT_003=41分，已對真實資料逐字驗算過。"""
    pytest.skip("TODO(Kiro): 依 02-data-contract.md §6 黃金驗收值表實作")
