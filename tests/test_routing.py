"""對應 m2-incident-routing/模組2C 第8節驗收測試(AC-C01~C10)，含真實路網資料驗證：
RD_TPE_004容量2500/RD_TPE_005容量4000/RD_TPE_008容量600(排除)/RD_TPE_006非直接相交(排除)。
"""

import pytest


def test_acc_001_golden_route_selection():
    """主RD_TPE_004/次RD_TPE_005/排除RD_TPE_006(NOT_DIRECTLY_INTERSECTING)、
    RD_TPE_008(CAPACITY_INSUFFICIENT)。"""
    pytest.skip("TODO(Kiro): 依 m2-incident-routing/模組2C AC-C01/C02 實作")


def test_reason_code_uses_spec00_nine_values_upper_snake_case():
    """回歸測試：ReasonCode 必須用 SPEC-00 §3.3 的九值 UPPER_SNAKE_CASE，
    不是模組2C文件裡殘留的 lower_snake_case 舊寫法。"""
    pytest.skip("TODO(Kiro): 依 m4-explanation-chain-and-orchestrator/SPEC-00 §3.3 實作")
