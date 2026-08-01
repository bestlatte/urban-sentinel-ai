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


# ---------------------------------------------------------------------------
# [2026-08-02] 假設的生命週期：新的假設情境不得沿用舊假設
#
# 使用者回報「chatbot 對是否是追問還是新問題很不懂」。真正的原因不是分類器，
# 是 `Session.assumptions` 同 key 覆蓋、不同 key 永久累加、永不過期，
# 而 prompt 明文要求把累積假設一併帶入 simulate_scenario。
# ---------------------------------------------------------------------------

from src.session.session_manager import (
    resolve_assumption_scope,
    drop_assumption,
    get_assumptions,
)


def test_scope_new_hypothesis_replaces():
    """「如果X」是一個獨立情境，不該把先前的假設拖進來。"""
    assert resolve_assumption_scope("如果光復南路坍塌會怎樣") == "replace"
    assert resolve_assumption_scope("假設市民大道四段飽和度到 0.98") == "replace"
    assert resolve_assumption_scope("萬一號誌全部故障呢") == "replace"


def test_scope_explicit_continuation_merges():
    """明說要疊加才疊加——「同時」「再加上」這種措辭。"""
    assert resolve_assumption_scope("如果光復南路同時也坍塌呢") == "merge"
    assert resolve_assumption_scope("假設在此基礎上市民大道再加上事故") == "merge"


def test_scope_plain_followup_carries():
    """對**現有情境**的追問必須留著假設。

    這條最容易被忽略但最重要：使用者問「那 ETE 呢」時，若把假設清掉，
    他會突然變成在問一個沒有假設的世界，而畫面上什麼跡象都沒有。
    """
    assert resolve_assumption_scope("那 ETE 呢") == "carry"
    assert resolve_assumption_scope("為什麼建議走市民大道") == "carry"
    assert resolve_assumption_scope("這起事件該怎麼處理") == "carry"


def test_new_hypothesis_does_not_carry_previous_assumptions():
    """端到端：先假設基隆路，再假設光復南路 → 第二題不得帶著基隆路。"""
    handle_message("s", "如果基隆路一段坍塌")
    record_response(
        "s", "如果基隆路一段坍塌", "答1",
        new_assumptions={"RD_TPE_003.status": "Closed"},
        assumption_scope="replace",
    )

    ctx = handle_message("s", "如果光復南路坍塌呢")
    assert ctx.assumption_scope == "replace"
    assert ctx.accumulated_assumptions == {}, "新的獨立情境不得沿用舊假設"
    assert ctx.dropped_assumptions == {"RD_TPE_003.status": "Closed"}, (
        "被丟掉的假設要回報，讓使用者知道系統做了這個決定"
    )


def test_replace_also_clears_the_stored_assumptions():
    """清掉的假設不能在下一輪追問（carry）時被撈回來。

    `handle_message()` 只決定「這輪不帶進 prompt」；若 session 裡還留著，
    下一句「那 ETE 呢」是 carry，就會把它們原封不動撈回來，等於白清一場。
    """
    handle_message("s", "如果基隆路一段坍塌")
    record_response("s", "如果基隆路一段坍塌", "答1",
                    new_assumptions={"RD_TPE_003.status": "Closed"},
                    assumption_scope="replace")

    handle_message("s", "如果光復南路坍塌呢")
    record_response("s", "如果光復南路坍塌呢", "答2",
                    new_assumptions={"RD_TPE_002.status": "Closed"},
                    assumption_scope="replace")

    ctx = handle_message("s", "那 ETE 呢")
    assert ctx.assumption_scope == "carry"
    assert ctx.accumulated_assumptions == {"RD_TPE_002.status": "Closed"}
    assert "RD_TPE_003.status" not in ctx.accumulated_assumptions


def test_explicit_merge_keeps_both():
    handle_message("s", "如果基隆路一段坍塌")
    record_response("s", "如果基隆路一段坍塌", "答1",
                    new_assumptions={"RD_TPE_003.status": "Closed"},
                    assumption_scope="replace")

    ctx = handle_message("s", "如果光復南路同時也坍塌呢")
    assert ctx.assumption_scope == "merge"
    assert ctx.accumulated_assumptions == {"RD_TPE_003.status": "Closed"}

    record_response("s", "如果光復南路同時也坍塌呢", "答2",
                    new_assumptions={"RD_TPE_002.status": "Closed"},
                    assumption_scope="merge")
    assert set(get_assumptions("s")) == {"RD_TPE_003.status", "RD_TPE_002.status"}


def test_drop_single_assumption():
    """chip 按 × 只移除那一項，其餘保留。"""
    handle_message("s", "q")
    record_response("s", "q", "a", new_assumptions={
        "RD_TPE_002.status": "Closed",
        "RD_TPE_004.saturation_score": 0.98,
    })
    remaining = drop_assumption("s", "RD_TPE_002.status")
    assert remaining == {"RD_TPE_004.saturation_score": 0.98}


def test_turn_stores_context_snapshot_for_change_detection():
    """快照要跟著 Turn 存下來，下一輪才 diff 得出「情況變了什麼」。"""
    handle_message("s", "q1")
    snap = {"trace_id": "TR-1", "primary": {"segment_id": "RD_TPE_004"}}
    record_response("s", "q1", "a1", context_snapshot=snap)

    ctx = handle_message("s", "q2")
    assert ctx.last_snapshot == snap
