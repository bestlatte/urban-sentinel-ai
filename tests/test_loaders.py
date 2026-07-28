"""對應 m1-data-ingestion/requirements.md 第六節驗收測試，逐條轉成 assert。

尤其第 1、2 項（真實 CSV 的 Roaming_User_Pct 字串解析 "40%"→0.40）與第 5 項
（SOP-6 黃金值：BS_TPE_101=0.40、BS_XY_ATT=0.30、BS_TPE_DOME≈0.05不觸發）——
這三項是本次審查中反覆用真實資料驗算過的關鍵斷言，不得放寬容錯誤差。
"""

import pytest

from src.loaders import load_data


def test_load_data_returns_normalized_bundle():
    pytest.skip("TODO(Kiro): 依 m1-data-ingestion/requirements.md 驗收測試 #1 實作")


def test_roaming_user_pct_percent_string_parsed_exactly():
    """真實CSV是 "40%" 字串，不是裸數字——這是最容易漏測的一步。"""
    pytest.skip("TODO(Kiro): 依 m1-data-ingestion/requirements.md 驗收測試 #2 實作")
