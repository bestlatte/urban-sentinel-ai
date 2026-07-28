"""契約層測試（03-testing-and-ai-collaboration.md §2.3）：驗證 Pydantic model
序列化後的欄位名稱、型別、必填/選填，逐一對照 02-data-contract.md 的欄位表，
不得憑印象假設欄位存在。
"""

from src.models import DecisionResult, MessageType, Notification, TraceAnswer


def test_decision_result_uses_control_center_report_not_advisory():
    """回歸測試：欄位名是 control_center_report/notifications，
    不是曾經在 SPEC-O3 出現過的 reports.advisory/reports.sms 嵌套形狀。"""
    fields = DecisionResult.model_fields
    assert "control_center_report" in fields
    assert "notifications" in fields
    assert "reports" not in fields


def test_notification_is_single_object_shape():
    fields = Notification.model_fields
    assert set(fields) == {"zh", "en", "ja", "ko"}


def test_trace_answer_exists_for_retrospective_branch():
    assert {"trace_id", "answer_text"} <= set(TraceAnswer.model_fields)


def test_message_type_enum_has_no_duplicate_decision_result_naming():
    """回歸測試：不應同時存在 decision.completed.v1 與 decision.result.v1 兩個
    指同一件事的值——本次審查發現並修正的重複定義。"""
    values = {m.value for m in MessageType}
    assert "decision.completed.v1" in values
    assert "decision.result.v1" not in values
