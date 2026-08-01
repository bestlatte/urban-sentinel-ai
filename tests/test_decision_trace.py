"""對應 SPEC-M4A 第6節十項驗收測試（全部決定性）。"""

import pytest

from src.decision_trace import (
    open_trace,
    record_step,
    reset_traces,
    ExcludedItem,
    Finding,
)


def setup_function():
    reset_traces()


# -- #1：同 trace 連續三次 record_step → 回傳 1, 2, 3 --
def test_sequential_sequence_numbers():
    open_trace("TR-TEST-001", ["§1"])
    s1 = record_step("TR-TEST-001", "A2", "PLAN", {}, {})
    s2 = record_step("TR-TEST-001", "R3", "CANDIDATE_FILTER", {}, {}, tool="CANDIDATE_FILTER")
    s3 = record_step("TR-TEST-001", "A3", "CALC_ETE", {}, {}, tool="CALC_ETE")
    assert s1 == 1
    assert s2 == 2
    assert s3 == 3


# -- #2：trace_id 空字串 → ValueError --
def test_empty_trace_id_raises():
    with pytest.raises(ValueError):
        open_trace("", ["§1"])


# -- #3：非法路段代碼（excluded / findings / subject 任一處）→ ValueError --
def test_invalid_segment_in_excluded_raises():
    open_trace("TR-TEST-002", ["§2"])
    with pytest.raises(ValueError):
        record_step("TR-TEST-002", "R4", "ROUTE_SELECT", {}, {},
                    excluded=[ExcludedItem(segment_id="INVALID_001", reason_code="CLOSED")])


def test_invalid_segment_in_findings_raises():
    open_trace("TR-TEST-003", ["§2"])
    with pytest.raises(ValueError):
        record_step("TR-TEST-003", "R4", "ROUTE_SELECT", {}, {},
                    findings=[Finding(finding_code="SATURATED_BUT_RETAINED",
                                      segment_ids=["BAD_SEGMENT"])])


def test_invalid_segment_in_subject_raises():
    open_trace("TR-TEST-004", ["§2"])
    with pytest.raises(ValueError):
        record_step("TR-TEST-004", "R4", "ROUTE_SELECT", {}, {},
                    subject_segment_ids=["NONEXISTENT_RD"])


# -- #4：未註冊 trace 寫入 → ValueError --
def test_unregistered_trace_raises():
    with pytest.raises(ValueError):
        record_step("NO-SUCH-TRACE", "A2", "PLAN", {}, {})


# -- #5：重複 open_trace → ValueError --
def test_duplicate_open_trace_raises():
    open_trace("TR-TEST-005", ["§1"])
    with pytest.raises(ValueError):
        open_trace("TR-TEST-005", ["§2"])


# -- #6：parent_seq 懸空 → ValueError --
def test_dangling_parent_seq_raises():
    open_trace("TR-TEST-006", ["§1"])
    record_step("TR-TEST-006", "A2", "PLAN", {}, {})  # seq=1
    with pytest.raises(ValueError):
        record_step("TR-TEST-006", "R3", "FILTER", {}, {}, parent_seq=99)


# -- #7：agent 不在 ActorCode → ValueError --
def test_invalid_actor_code_raises():
    open_trace("TR-TEST-007", ["§1"])
    with pytest.raises(ValueError):
        record_step("TR-TEST-007", "INVALID_AGENT", "PLAN", {}, {})


# -- #8：reason_code 不在九值列舉 → ValueError --
def test_invalid_reason_code_raises():
    open_trace("TR-TEST-008", ["§2"])
    with pytest.raises(ValueError):
        record_step("TR-TEST-008", "R4", "ROUTE_SELECT", {}, {},
                    excluded=[ExcludedItem(segment_id="RD_TPE_006",
                                           reason_code="made_up_reason")])


# -- #9：finding_code=SATURATED_BUT_RETAINED 且 segment 合法 → 寫入成功 --
def test_saturated_but_retained_finding_succeeds():
    open_trace("TR-TEST-009", ["§2"])
    seq = record_step("TR-TEST-009", "R4", "ROUTE_SELECT", {}, {},
                      findings=[Finding(
                          finding_code="SATURATED_BUT_RETAINED",
                          segment_ids=["RD_TPE_004"],
                          evidence={"saturation_score": 0.88},
                      )])
    assert seq == 1


# -- #10：duration_ms 缺漏 → 寫入成功 --
def test_duration_ms_optional():
    open_trace("TR-TEST-010", ["§1"])
    seq = record_step("TR-TEST-010", "A2", "PLAN", {}, {}, duration_ms=None)
    assert seq == 1


# -- 額外：valid parent_seq --
def test_valid_parent_seq_succeeds():
    open_trace("TR-TEST-011", ["§1"])
    s1 = record_step("TR-TEST-011", "A2", "DISPATCH", {}, {})
    s2 = record_step("TR-TEST-011", "R3", "FILTER", {}, {}, parent_seq=s1)
    assert s2 == 2


# -- 額外：triggered_by 格式不合法 --
def test_invalid_triggered_by_format_raises():
    with pytest.raises(ValueError):
        open_trace("TR-TEST-012", ["bad_format"])


# ===========================================================================
# Phase 5.2: M4B 解釋生成層測試
# ===========================================================================

from src.decision_trace import (
    resolve_segment_id,
    generate_report_explanation,
    answer_trace_query,
)
import os


# -- M4B #2：路段名無法識別 → 固定文字 --
def test_answer_trace_query_not_found():
    open_trace("TR-M4B-01", ["§1"])
    record_step("TR-M4B-01", "A2", "PLAN", {}, {})
    result = answer_trace_query("TR-M4B-01", "今天天氣很好")
    assert "無法識別" in result


# -- M4B #1：查無路段的追問 → 固定文字 --
def test_answer_trace_query_segment_not_in_trace():
    """路段識別成功但不在 trace 紀錄中。"""
    open_trace("TR-M4B-02", ["§2"])
    record_step("TR-M4B-02", "R4", "ROUTE_SELECT", {}, {},
                subject_segment_ids=["RD_TPE_004"])
    # 問一個存在但不在 trace 中的路段
    result = answer_trace_query("TR-M4B-02", "基隆路一段的狀況如何")
    assert "未列入本次判斷" in result


# -- M4B #3：最長匹配 --
def test_resolve_segment_id_longest_match():
    """有多個子字串命中時，取最長的。"""
    from src.decision_trace import _ensure_segment_name_map, _SEGMENT_NAME_MAP
    _ensure_segment_name_map()
    # 確認有「敦化南路一段」和「敦化南路二段」兩條路
    has_dunhua_1 = any("敦化南路一段" in name for name in _SEGMENT_NAME_MAP)
    has_dunhua_2 = any("敦化南路二段" in name for name in _SEGMENT_NAME_MAP)
    if has_dunhua_1 and has_dunhua_2:
        result = resolve_segment_id("敦化南路一段那邊怎麼樣")
        assert result != "AMBIGUOUS"  # 一段比二段精確命中
        assert result.startswith("RD_TPE_")


# -- M4B #4：excluded 命中 --
def test_answer_trace_query_excluded_hit(monkeypatch):
    monkeypatch.setenv("USE_BEDROCK", "false")
    open_trace("TR-M4B-04", ["§2"])
    record_step("TR-M4B-04", "R4", "ROUTE_SELECT", {}, {},
                excluded=[ExcludedItem(segment_id="RD_TPE_008", reason_code="CAPACITY_INSUFFICIENT")])
    result = answer_trace_query("TR-M4B-04", "延吉街為什麼不能走")
    # 應能找到紀錄並回傳（降級模式顯示原始紀錄）
    assert "CAPACITY_INSUFFICIENT" in result


# -- M4B #5：findings 命中 --
def test_answer_trace_query_findings_hit(monkeypatch):
    monkeypatch.setenv("USE_BEDROCK", "false")
    open_trace("TR-M4B-05", ["§2"])
    record_step("TR-M4B-05", "R4", "ROUTE_SELECT", {}, {},
                findings=[Finding(finding_code="SATURATED_BUT_RETAINED",
                                  segment_ids=["RD_TPE_004"])])
    result = answer_trace_query("TR-M4B-05", "市民大道四段有什麼風險")
    assert "SATURATED_BUT_RETAINED" in result


# -- M4B #6：報告冪等 --
def test_generate_report_explanation_raises_in_fallback_mode(monkeypatch):
    """USE_BEDROCK=false（保底模式）→ 拋 RuntimeError，由呼叫端降級。"""
    monkeypatch.setenv("USE_BEDROCK", "false")
    open_trace("TR-M4B-06", ["§1"])
    record_step("TR-M4B-06", "A2", "PLAN", {}, {})
    with pytest.raises(RuntimeError):
        generate_report_explanation("TR-M4B-06")


# -- M4B #7：報告生成於空 trace → ValueError --
def test_generate_report_explanation_empty_trace_raises():
    open_trace("TR-M4B-07", ["§1"])
    with pytest.raises(ValueError):
        generate_report_explanation("TR-M4B-07")


# -- M4B #8：LLM 失敗降級（追問）→ 回固定前綴 + 原始紀錄 --
def test_answer_trace_query_fallback(monkeypatch):
    monkeypatch.setenv("USE_BEDROCK", "false")
    open_trace("TR-M4B-08", ["§2"])
    record_step("TR-M4B-08", "R4", "ROUTE_SELECT", {}, {},
                subject_segment_ids=["RD_TPE_004"])
    result = answer_trace_query("TR-M4B-08", "市民大道四段狀況")
    assert "系統暫時無法生成說明" in result or "sequence_no" in result


# ===========================================================================
# M4B LLM 生成路徑（USE_BEDROCK=true，以 mock 取代 Bedrock 呼叫）
#
# 上面那批測試涵蓋的是保底模式與確定性分支；這批專測「LLM 真的被接上之後」
# 的行為：冪等、失敗處理、以及 SPEC-M4B §5 提示詞契約。
# ===========================================================================

import json

from src import decision_trace as dt


class _LlmSpy:
    """代替 `_invoke_m4b_llm`：記錄呼叫次數與收到的輸入。"""

    def __init__(self, response="【決策說明】依 SOP-2 排除 RD_TPE_008。", error=None):
        self.response = response
        self.error = error
        self.calls = 0
        self.last_input = None

    def __call__(self, user_message):
        self.calls += 1
        self.last_input = user_message
        if self.error:
            raise self.error
        return self.response


# -- M4B §5：提示詞契約四條規則，不得增減 --
def test_m4b_prompt_contract_has_exactly_four_rules():
    lines = [ln for ln in dt.M4B_SYSTEM_PROMPT.splitlines() if ln.strip()[:2] in
             ("1.", "2.", "3.", "4.", "5.")]
    assert len(lines) == 4
    assert "不得添加任何未出現的細節" in dt.M4B_SYSTEM_PROMPT
    assert "sop_ref" in dt.M4B_SYSTEM_PROMPT
    assert "紀錄中未包含此資訊" in dt.M4B_SYSTEM_PROMPT
    assert "繁體中文" in dt.M4B_SYSTEM_PROMPT


# -- M4B #6：報告冪等（第二次不呼叫 LLM，字串相同）--
def test_generate_report_explanation_is_idempotent(monkeypatch):
    monkeypatch.setenv("USE_BEDROCK", "true")
    spy = _LlmSpy()
    monkeypatch.setattr(dt, "_invoke_m4b_llm", spy)

    open_trace("TR-M4B-10", ["§2"])
    record_step("TR-M4B-10", "R4", "ROUTE_SELECT", {}, {},
                subject_segment_ids=["RD_TPE_004"])

    first = generate_report_explanation("TR-M4B-10")
    second = generate_report_explanation("TR-M4B-10")

    assert first == second == spy.response
    assert spy.calls == 1


def test_generate_report_explanation_input_contains_trace_facts(monkeypatch):
    """輸入必須含 TraceMeta.triggered_by 與結構化 steps（SPEC-M4B §5）。"""
    monkeypatch.setenv("USE_BEDROCK", "true")
    spy = _LlmSpy()
    monkeypatch.setattr(dt, "_invoke_m4b_llm", spy)

    open_trace("TR-M4B-11", ["§2"])
    record_step("TR-M4B-11", "R4", "ROUTE_SELECT", {}, {},
                excluded=[ExcludedItem(segment_id="RD_TPE_008",
                                       reason_code="CAPACITY_INSUFFICIENT")])
    generate_report_explanation("TR-M4B-11")

    payload = json.loads(spy.last_input)
    assert payload["triggered_by"] == ["§2"]
    assert payload["steps"][0]["excluded"][0]["reason_code"] == "CAPACITY_INSUFFICIENT"


# -- M4B #9：報告 LLM 失敗 → 拋例外，不回傳部分內容 --
def test_generate_report_explanation_propagates_llm_failure(monkeypatch):
    monkeypatch.setenv("USE_BEDROCK", "true")
    spy = _LlmSpy(error=RuntimeError("bedrock throttled"))
    monkeypatch.setattr(dt, "_invoke_m4b_llm", spy)

    open_trace("TR-M4B-12", ["§1"])
    record_step("TR-M4B-12", "A2", "PLAN", {}, {})

    with pytest.raises(RuntimeError, match="throttled"):
        generate_report_explanation("TR-M4B-12")
    # 失敗不得進快取，否則後續重試會拿到殘缺結果
    assert "TR-M4B-12" not in dt._EXPLANATION_CACHE


# -- M4B #8：追問 LLM 失敗 → 降級顯示原始紀錄，不拋出 --
def test_answer_trace_query_degrades_on_llm_failure(monkeypatch):
    monkeypatch.setenv("USE_BEDROCK", "true")
    spy = _LlmSpy(error=RuntimeError("bedrock down"))
    monkeypatch.setattr(dt, "_invoke_m4b_llm", spy)

    open_trace("TR-M4B-13", ["§2"])
    record_step("TR-M4B-13", "R4", "ROUTE_SELECT", {}, {},
                excluded=[ExcludedItem(segment_id="RD_TPE_008",
                                       reason_code="CAPACITY_INSUFFICIENT")])

    result = answer_trace_query("TR-M4B-13", "延吉街為什麼不能走")
    assert "系統暫時無法生成說明" in result
    assert "CAPACITY_INSUFFICIENT" in result


def test_answer_trace_query_uses_llm_when_records_hit(monkeypatch):
    monkeypatch.setenv("USE_BEDROCK", "true")
    spy = _LlmSpy(response="延吉街容量不足，依 SOP-2 排除。")
    monkeypatch.setattr(dt, "_invoke_m4b_llm", spy)

    open_trace("TR-M4B-14", ["§2"])
    record_step("TR-M4B-14", "R4", "ROUTE_SELECT", {}, {},
                excluded=[ExcludedItem(segment_id="RD_TPE_008",
                                       reason_code="CAPACITY_INSUFFICIENT")])

    result = answer_trace_query("TR-M4B-14", "延吉街為什麼不能走")
    assert result == spy.response
    assert spy.calls == 1
    payload = json.loads(spy.last_input)
    assert payload["question"] == "延吉街為什麼不能走"
    assert payload["target_segment_id"] == "RD_TPE_008"


# -- M4B #1/#2：確定性分支不得呼叫 LLM --
@pytest.mark.parametrize(
    "question,expected",
    [
        ("今天天氣很好", "無法識別"),
        ("基隆路一段的狀況如何", "未列入本次判斷"),
    ],
)
def test_deterministic_branches_never_call_llm(monkeypatch, question, expected):
    monkeypatch.setenv("USE_BEDROCK", "true")
    spy = _LlmSpy()
    monkeypatch.setattr(dt, "_invoke_m4b_llm", spy)

    trace_id = f"TR-M4B-15-{abs(hash(question)) % 1000}"
    open_trace(trace_id, ["§2"])
    record_step(trace_id, "R4", "ROUTE_SELECT", {}, {},
                subject_segment_ids=["RD_TPE_004"])

    result = answer_trace_query(trace_id, question)
    assert expected in result
    assert spy.calls == 0
