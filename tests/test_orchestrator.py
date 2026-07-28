"""對應 m4-explanation-chain-and-orchestrator/SPEC-O1/O2/O3 全部驗收測試 +
m5-api-orchestrator-dashboard/design.md 的 30 個 Correctness Properties
（用 hypothesis 性質測試，見該文件「Testing Strategy」節）。

本檔先列核心回歸測試；30個Property的完整套件由 Kiro 依 design.md 逐一實作
（每個測試函式標註 `# Feature: m5-orchestrator-dashboard, Property {n}: {text}`）。
"""

import pytest


def test_post_what_if_routes_to_whatif_for_hypothetical_question():
    pytest.skip("TODO(Kiro): 依 SPEC-O3 §4 驗收測試 #1 實作")


def test_post_what_if_routes_to_trace_answer_for_retrospective_question():
    """回歸測試：回溯追問分支回傳 trace.answered.v1/TraceAnswer，
    不是硬塞進 WhatIfResult（本次審查新增的正確設計）。"""
    pytest.skip("TODO(Kiro): 依 SPEC-O3 §4 驗收測試 #2 + m5-api-orchestrator-dashboard R2.5a 實作")


def test_decision_completed_message_type_not_decision_result():
    """回歸測試：WS推播完整DecisionResult用 decision.completed.v1，
    不是 SPEC-O3 早期版本寫的 decision.result.v1（兩份文件曾經對同一事件用不同名字）。"""
    pytest.skip("TODO(Kiro): 依 04-system-architecture.md §5 總表實作")


def test_acc001_golden_regression_full_pipeline():
    """ACC_001 全流程：主004/次005/排除006、008/ETE 90分/恢復23:40。"""
    pytest.skip("TODO(Kiro): 依 SPEC-O2 驗收測試表「黃金值回歸」實作")
