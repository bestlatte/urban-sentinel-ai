"""對應 W2-session-manager/design.md 第四節。"""

from src.session.session_manager import (
    handle_message,
    record_response,
    clear_session,
    SESSION_STORE,
    MAX_HISTORY,
)
from src.session.models import W1Context, Session


def setup_function():
    """每個測試前清空 SESSION_STORE。"""
    SESSION_STORE.clear()


# -- 4.1 handle_message --
def test_handle_message_creates_session_and_builds_context():
    ctx = handle_message("sess-1", "如果BL17到40000人會怎樣")
    assert isinstance(ctx, W1Context)
    assert ctx.session_id == "sess-1"
    assert ctx.new_message == "如果BL17到40000人會怎樣"
    assert ctx.history == []
    assert ctx.accumulated_assumptions == {}
    # session 確實被建立
    assert "sess-1" in SESSION_STORE


def test_handle_message_reuses_existing_session():
    handle_message("sess-1", "第一次問")
    record_response("sess-1", "第一次問", "第一次答")
    ctx = handle_message("sess-1", "第二次問")
    assert len(ctx.history) == 1
    assert ctx.history[0].user_message == "第一次問"


# -- 4.2 record_response --
def test_record_response_takes_user_message_as_parameter():
    """回歸測試：沒有 _pending_message 暫存屬性。"""
    handle_message("sess-1", "問題")
    record_response("sess-1", "問題", "回答", triggered_sops=[2, 7])
    session = SESSION_STORE["sess-1"]
    assert len(session.history) == 1
    assert session.history[0].user_message == "問題"
    assert session.history[0].ai_response == "回答"
    assert session.history[0].triggered_sops == [2, 7]
    # 確認 Session 物件上沒有 _pending_message
    assert not hasattr(session, "_pending_message")


def test_record_response_updates_assumptions():
    handle_message("sess-1", "假設BL17到40000")
    record_response(
        "sess-1", "假設BL17到40000", "好的",
        new_assumptions={"BS_MRT_BL17.User_Count": 40000},
    )
    session = SESSION_STORE["sess-1"]
    assert session.assumptions == {"BS_MRT_BL17.User_Count": 40000}


def test_record_response_overwrites_same_key():
    """同一 key 被重新假設時覆蓋舊值。"""
    handle_message("sess-1", "first")
    record_response("sess-1", "first", "ok", new_assumptions={"BS_MRT_BL17.User_Count": 30000})
    record_response("sess-1", "second", "ok", new_assumptions={"BS_MRT_BL17.User_Count": 40000})
    assert SESSION_STORE["sess-1"].assumptions["BS_MRT_BL17.User_Count"] == 40000


def test_record_response_ignores_cleared_session():
    """session 已被清除後收到 record_response，靜默忽略不報錯。"""
    handle_message("sess-1", "問題")
    clear_session("sess-1")
    # 不應拋例外
    record_response("sess-1", "問題", "回答")


# -- history cap --
def test_history_capped_at_max_10_turns():
    handle_message("sess-1", "init")
    for i in range(15):
        record_response("sess-1", f"q{i}", f"a{i}")
    session = SESSION_STORE["sess-1"]
    assert len(session.history) == MAX_HISTORY
    # 最早的應該被裁切，保留最後 10 輪
    assert session.history[0].user_message == "q5"


def test_handle_message_returns_capped_history():
    handle_message("sess-1", "init")
    for i in range(15):
        record_response("sess-1", f"q{i}", f"a{i}")
    ctx = handle_message("sess-1", "new question")
    assert len(ctx.history) == MAX_HISTORY


# -- 4.3 clear_session --
def test_clear_session_removes_session():
    handle_message("sess-1", "test")
    assert "sess-1" in SESSION_STORE
    clear_session("sess-1")
    assert "sess-1" not in SESSION_STORE


def test_clear_session_nonexistent_does_not_crash():
    """清除不存在的 session 不報錯。"""
    clear_session("nonexistent")  # 不應拋例外


# -- accumulated_assumptions 傳遞 --
def test_accumulated_assumptions_passed_to_context():
    handle_message("sess-1", "q1")
    record_response("sess-1", "q1", "a1", new_assumptions={"RD_TPE_002.status": "Closed"})
    ctx = handle_message("sess-1", "q2")
    assert ctx.accumulated_assumptions == {"RD_TPE_002.status": "Closed"}
