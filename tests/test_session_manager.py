"""對應 W2-session-manager/tasks.md（已修正版，不含 _pending_message 暫存機制）。"""

import pytest


def test_handle_message_creates_session_and_builds_context():
    pytest.skip("TODO(Kiro): 依 W2-session-manager/design.md 第4.1節實作")


def test_history_capped_at_max_10_turns():
    pytest.skip("TODO(Kiro): 依 W2-session-manager/tasks.md 完成標準實作")


def test_record_response_takes_user_message_as_parameter():
    """回歸測試：確認沒有 _pending_message 這個屬性殘留（本次審查移除的舊設計）。"""
    pytest.skip("TODO(Kiro): 依 W2-session-manager/design.md 第4.2節實作")
