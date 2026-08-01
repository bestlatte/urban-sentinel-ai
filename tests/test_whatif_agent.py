"""W1 What-if Agent 的回歸測試。

這個檔案在 2026-08-01 之前不存在——W1 的整條結構化欄位鏈壞掉沒有被任何測試
攔住，正是因為沒有測試。每一個測試都對應一個實測確認過的缺陷，不是為了湊
覆蓋率而寫的。

註：只測確定性部分（訊息解析、降級路徑、假設累積）。真的呼叫 Bedrock 的行為
適用 `03-testing-and-ai-collaboration.md` §2.2 結構性事實斷言，不在單元測試裡跑。
"""

from __future__ import annotations

import json

import pytest

from src.agent import whatif_agent
from src.agent.response_formatter import (
    ToolInvocation,
    extract_tool_invocations,
    format_response,
)


# ---------------------------------------------------------------------------
# 測試替身：仿真 Strands 的 agent.messages 結構
# ---------------------------------------------------------------------------


def _tool_use(tool_use_id: str, name: str, tool_input: dict) -> dict:
    return {
        "role": "assistant",
        "content": [{"toolUse": {"toolUseId": tool_use_id, "name": name, "input": tool_input}}],
    }


def _tool_result(tool_use_id: str, payload, status: str = "success") -> dict:
    """Strands 把工具回傳值 json.dumps 後放進 {"text": ...}——這裡照做，
    否則測試會通過但真實情境仍然壞掉（原本的 bug 就是這樣被漏掉的）。"""
    return {
        "role": "user",
        "content": [
            {
                "toolResult": {
                    "toolUseId": tool_use_id,
                    "status": status,
                    "content": [{"text": json.dumps(payload, ensure_ascii=False)}],
                }
            }
        ],
    }


class FakeAgentResult:
    """仿真 Strands `AgentResult`。

    刻意**只**提供實測存在的欄位（message/stop_reason）。原本的
    `_extract_tool_results()` 找的是 `.messages` 與 `.tool_results`，
    這個替身沒有那兩個屬性——若有人改回舊寫法，測試會立刻紅。
    """

    def __init__(self, text: str):
        self.stop_reason = "end_turn"
        self.message = {"role": "assistant", "content": [{"text": text}]}


class FakeContext:
    def __init__(self, new_message="如果人數增加到四萬呢？", history=None, assumptions=None):
        self.new_message = new_message
        self.history = history or []
        self.accumulated_assumptions = assumptions or {}


SOP_PAYLOAD = {
    "sections": [
        {"section_number": 2, "title": "車禍與路障應變", "content": "原文…", "relevance_score": 1.0}
    ],
    "retrieval_source": "local_fallback",
}

SIM_PAYLOAD = {
    "rule_hits": [{"clause_id": "SOP-3", "evidence": {"field": "user_count", "value": 40000}}],
    "route_plan": {"primary": {"segment_id": "RD_TPE_004", "name": "市民大道四段"}},
    "ete": {"minutes": 90, "recovery_at": "2026-05-20 23:40"},
    "judgment_basis": "主因條款 — SOP-3：BS_MRT_BL17 user_count = 40000（門檻 30000）",
    "current_data_snapshot": {"applied_overrides": {"BS_MRT_BL17.User_Count": 40000}},
    "actions": ["通知北捷啟動過站不停措施，調度接駁專車"],
}


# ---------------------------------------------------------------------------
# 破洞①：tool 結果抽取
# ---------------------------------------------------------------------------


def test_extract_tool_invocations_pairs_use_with_result():
    """toolUse 與 toolResult 靠 toolUseId 配對，且結果字串要被 parse 回結構。"""
    messages = [
        {"role": "user", "content": [{"text": "問題"}]},
        _tool_use("tu_1", "query_sop", {"question": "塌陷"}),
        _tool_result("tu_1", SOP_PAYLOAD),
    ]

    invocations = extract_tool_invocations(messages)

    assert len(invocations) == 1
    assert invocations[0].name == "query_sop"
    assert invocations[0].input == {"question": "塌陷"}
    assert invocations[0].output["sections"][0]["section_number"] == 2
    assert invocations[0].ok is True


def test_agent_result_without_messages_yields_no_invocations():
    """回歸測試：AgentResult 本身沒有 .messages／.tool_results。

    原實作對 AgentResult 猜三種屬性，三個都不存在，於是永遠回空 dict——
    整條結構化欄位鏈因此死掉。正確來源是另外傳進來的 agent.messages。
    """
    result = FakeAgentResult("純文字回覆")
    assert not hasattr(result, "messages")
    assert not hasattr(result, "tool_results")

    response = format_response(result, FakeContext(), messages=None)
    assert response.tools_called == []
    assert response.intent_type == "chitchat"


def test_format_response_fills_structured_fields_from_messages():
    """核心回歸測試：simulate_scenario 的結果必須真的填進 W1Response。"""
    messages = [
        {"role": "user", "content": [{"text": "如果人數到四萬"}]},
        _tool_use("tu_1", "query_sop", {"question": "人流"}),
        _tool_result("tu_1", SOP_PAYLOAD),
        _tool_use("tu_2", "simulate_scenario", {"assumptions": {"BS_MRT_BL17.User_Count": 40000}}),
        _tool_result("tu_2", SIM_PAYLOAD),
    ]

    response = format_response(
        FakeAgentResult("結論：人流會觸發 SOP-3。\n\n延伸問題\n1. 甲\n2. 乙\n3. 丙"),
        FakeContext(),
        messages=messages,
    )

    assert response.intent_type == "whatif_simulation"
    assert response.tools_called == ["query_sop", "simulate_scenario"]
    assert [s["section_number"] for s in response.triggered_sops] == [2]
    assert response.ete == {"minutes": 90, "recovery_at": "2026-05-20 23:40"}
    assert response.judgment_basis.startswith("主因條款")
    assert response.expected_actions == ["通知北捷啟動過站不停措施，調度接駁專車"]
    assert response.current_data["applied_overrides"] == {"BS_MRT_BL17.User_Count": 40000}
    assert response.source_mode == "full"
    assert response.suggested_questions == ["甲", "乙", "丙"]


def test_route_impact_is_flattened_to_display_strings():
    """回歸測試：`route_impact` 必須是字串，不能是 RoutePlan 物件。

    前端 `chat-render.js` 做的是 `escapeHtml(data.route_impact.primary)`——
    它要的是路段名。原本塞的是整個 `RoutePlan.model_dump()`，於是
    `data.route_impact.primary` 是個 dict，JS 轉字串後畫面上顯示
    **`[object Object]`**。卡片的「路網影響」那一列從來沒對過。
    """
    payload = dict(SIM_PAYLOAD)
    payload["route_plan"] = {
        "primary": {"segment_id": "RD_TPE_004", "name": "市民大道四段"},
        "secondary": {"segment_id": "RD_TPE_005", "name": "仁愛路四段"},
        "excluded": [{"segment_id": "RD_TPE_008", "name": "延吉街"}],
    }
    messages = [
        _tool_use("tu_1", "simulate_scenario", {"assumptions": {}}),
        _tool_result("tu_1", payload),
    ]

    response = format_response(FakeAgentResult("結論"), FakeContext(), messages=messages)

    assert response.route_impact == {
        "primary": "市民大道四段",
        "secondary": "仁愛路四段",
        "blocked": ["延吉街"],
    }
    for value in response.route_impact.values():
        flat = value if isinstance(value, list) else [value]
        assert all(isinstance(v, str) for v in flat), "route_impact 必須全是字串"


def test_judgment_steps_passed_through_to_response():
    """結構化推理鏈必須送達前端，否則 renderReasoningChain() 畫不出東西。"""
    payload = dict(SIM_PAYLOAD)
    payload["judgment_steps"] = [
        {"stage": "rules", "title": "命中條款", "items": [{"clause_id": "SOP-3"}], "extra": {}}
    ]
    messages = [
        _tool_use("tu_1", "simulate_scenario", {"assumptions": {}}),
        _tool_result("tu_1", payload),
    ]

    response = format_response(FakeAgentResult("結論"), FakeContext(), messages=messages)

    assert len(response.judgment_steps) == 1
    assert response.judgment_steps[0]["stage"] == "rules"


def test_judgment_steps_defaults_to_empty_when_absent():
    """舊版 payload（沒有 judgment_steps）不得讓格式化拋錯。"""
    messages = [
        _tool_use("tu_1", "simulate_scenario", {"assumptions": {}}),
        _tool_result("tu_1", SIM_PAYLOAD),
    ]

    response = format_response(FakeAgentResult("結論"), FakeContext(), messages=messages)

    assert response.judgment_steps == []


def test_merges_sop_sections_across_repeated_queries():
    """Agent 換問法重查時，兩次查到的條款都要保留（實測會查兩次）。"""
    messages = [
        _tool_use("tu_1", "query_sop", {"question": "a"}),
        _tool_result("tu_1", {"sections": [
            {"section_number": 2, "title": "車禍", "content": "x", "relevance_score": 0.33}
        ]}),
        _tool_use("tu_2", "query_sop", {"question": "b"}),
        _tool_result("tu_2", {"sections": [
            {"section_number": 5, "title": "號誌故障", "content": "y", "relevance_score": 0.67},
            {"section_number": 2, "title": "車禍", "content": "x", "relevance_score": 1.0},
        ]}),
    ]

    response = format_response(FakeAgentResult("回覆"), FakeContext(), messages=messages)

    # 依相關度排序、section_number 去重取最高分
    assert [s["section_number"] for s in response.triggered_sops] == [2, 5]
    assert response.triggered_sops[0]["relevance_score"] == 1.0


def test_failed_simulation_marks_source_mode_degraded():
    """simulate_scenario 回 fallback 時 source_mode 必須是 degraded。"""
    messages = [
        _tool_use("tu_1", "simulate_scenario", {"assumptions": {}}),
        _tool_result("tu_1", {"status": "unavailable", "message": "模組不可用", "fallback": True}),
    ]

    response = format_response(FakeAgentResult("回覆"), FakeContext(), messages=messages)
    assert response.source_mode == "degraded"


def test_pure_sop_question_is_not_marked_degraded():
    """純 SOP 問答不需要決策模組，不該被標成降級。"""
    messages = [
        _tool_use("tu_1", "query_sop", {"question": "塌陷"}),
        _tool_result("tu_1", SOP_PAYLOAD),
    ]

    response = format_response(FakeAgentResult("回覆"), FakeContext(), messages=messages)
    assert response.intent_type == "sop_query"
    assert response.source_mode == "full"


def test_legacy_dict_interface_still_works():
    """舊的 {"tool_results": {...}} 介面要保持相容。"""
    response = format_response(
        {"text": "回覆", "tool_results": {"query_sop": SOP_PAYLOAD}},
        FakeContext(),
    )
    assert response.tools_called == ["query_sop"]
    assert [s["section_number"] for s in response.triggered_sops] == [2]


# ---------------------------------------------------------------------------
# 破洞②：假設累積
# ---------------------------------------------------------------------------


def test_assumptions_extracted_for_session_accumulation():
    """回歸測試：本輪假設要交給 W2 累積，否則多輪對話會失去上下文。

    原本 `_extract_new_assumptions()` 直接 return None，`session.assumptions`
    永遠是空的，「如果 A…」→「那再加上 B 呢？」整個功能等於不存在。
    """
    messages = [
        _tool_use("tu_1", "simulate_scenario", {"assumptions": {"BS_MRT_BL17.User_Count": 40000}}),
        _tool_result("tu_1", SIM_PAYLOAD),
    ]
    response = format_response(FakeAgentResult("回覆"), FakeContext(), messages=messages)

    assert whatif_agent._assumptions_from_response(response) == {
        "BS_MRT_BL17.User_Count": 40000
    }


def test_assumptions_not_recorded_when_simulation_failed():
    """模擬失敗時不得把假設記進 session——否則下一輪會帶著從未生效的條件繼續推。"""
    messages = [
        _tool_use("tu_1", "simulate_scenario", {"assumptions": {"RD_TPE_002.status": "Closed"}}),
        _tool_result("tu_1", {"status": "unavailable", "fallback": True}),
    ]
    response = format_response(FakeAgentResult("回覆"), FakeContext(), messages=messages)

    assert whatif_agent._assumptions_from_response(response) is None


def test_merge_assumptions_later_call_wins():
    """同一輪多次呼叫時，後面的假設覆蓋前面的同名 key。"""
    invocations = [
        ToolInvocation("simulate_scenario", "1", {"assumptions": {"a": 1, "b": 2}}),
        ToolInvocation("simulate_scenario", "2", {"assumptions": {"b": 3}}),
    ]
    assert whatif_agent._merge_assumptions(invocations) == {"a": 1, "b": 3}


# ---------------------------------------------------------------------------
# 破洞③：保底模式
# ---------------------------------------------------------------------------


def test_use_bedrock_false_degrades_without_calling_agent(monkeypatch):
    """USE_BEDROCK=false 時不得建立 Agent、不得送出請求（00-tech-stack.md §6）。"""
    monkeypatch.setenv("USE_BEDROCK", "false")

    def explode():
        raise AssertionError("保底模式下不該建立 Agent")

    monkeypatch.setattr(whatif_agent, "create_whatif_agent", explode)

    response = whatif_agent.process_whatif(FakeContext("如果人數增加到四萬？"))

    assert response.source_mode == "degraded"
    assert response.intent_type == "sop_query"


def test_agent_creation_failure_degrades_not_raises(monkeypatch):
    """缺套件/缺憑證時要降級，不得讓例外往上拋（永不沉默原則）。"""
    monkeypatch.setenv("USE_BEDROCK", "true")

    def explode():
        raise RuntimeError("模擬缺 AWS 憑證")

    monkeypatch.setattr(whatif_agent, "create_whatif_agent", explode)
    monkeypatch.setattr(whatif_agent, "_current_incident_record", lambda: None)

    response = whatif_agent.process_whatif(FakeContext("如果封閉忠孝東路？"))
    assert response.source_mode == "degraded"


# ---------------------------------------------------------------------------
# 破洞④：逾時護欄
# ---------------------------------------------------------------------------


def test_agent_timeout_degrades(monkeypatch):
    """Agent 超過時限要降級，不得無限期卡住對話。"""
    monkeypatch.setenv("USE_BEDROCK", "true")
    monkeypatch.setattr(whatif_agent, "_current_incident_record", lambda: None)

    class HangingAgent:
        messages: list = []

        def __call__(self, prompt):
            import time

            time.sleep(5)
            return FakeAgentResult("太慢了")

    monkeypatch.setattr(whatif_agent, "create_whatif_agent", lambda: HangingAgent())
    monkeypatch.setattr(whatif_agent, "AGENT_TIMEOUT_S", 0.2)

    response = whatif_agent.process_whatif(FakeContext("如果封閉忠孝東路？"))
    assert response.source_mode == "degraded"


def test_run_with_timeout_raises_before_work_finishes():
    """`llm.run_with_timeout()` 必須在時限到就放棄，不能等工作執行緒收工。"""
    import time

    from src.llm import run_with_timeout

    started = time.monotonic()
    with pytest.raises(TimeoutError):
        run_with_timeout(lambda: time.sleep(5), 0.2, label="測試")
    assert time.monotonic() - started < 2.0


# ---------------------------------------------------------------------------
# 方案B：情境建議書的觸發判斷
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "text, expected",
    [
        # --- 真的沒有內容 ---
        ("如果", True),          # 實測：這兩個字讓 Agent 跑 30 秒生一篇廢話
        ("如果？", True),
        ("如果呢？", True),
        ("假設", True),
        ("怎麼辦", True),        # 沒有主詞，辦什麼無從得知
        ("?", True),
        ("", True),
        ("   ", True),
        # --- 有內容，不得被擋 ---
        ("如果市民大道四段飽和度到 0.98 呢？", False),
        ("目前是什麼應變等級？", False),
        ("如果封路呢", False),   # 有主詞「封路」，是完整的假設
    ],
)
def test_incomplete_input_short_circuits(text, expected):
    """不完整輸入必須被確定性擋掉，不得走 LLM。"""
    assert whatif_agent.is_incomplete_input(text) is expected


@pytest.mark.parametrize("text", ["你是誰", "你好", "塞車", "SOP-2", "A級", "路況"])
def test_short_but_complete_questions_are_not_incomplete(text):
    """回歸測試：短的中文問句不等於沒打完。

    原本第一關是 `len(stripped) < 4`（拿長度當「有沒有內容」的代理指標）。中文
    問句密度很高，實測這些**完整且可回答**的問題全被判成不完整輸入：

        使用者問「你是誰」→ 回「看起來問題還沒打完。請描述完整的假設情境…」
        後面接三個 What-if 範例問句。

    使用者的體感就是 chatbot 壞了——他問的是一個再正常不過的問題。
    現在只看「拿掉前瞻詞與標點後還剩不剩實質內容」，不看長度。
    """
    assert whatif_agent.is_incomplete_input(text) is False


def test_incomplete_input_response_costs_no_llm(monkeypatch):
    """回歸測試：「如果」兩個字不得建立 Agent、不得呼叫 LLM。

    這是使用者實測回報的問題——打了半句話就卡三十秒，最後拿到一篇
    「請問您想問什麼呢？」外加一堆模型自己編的範例。
    """
    monkeypatch.setenv("USE_BEDROCK", "true")

    def explode():
        raise AssertionError("不完整輸入不該建立 Agent")

    monkeypatch.setattr(whatif_agent, "create_whatif_agent", explode)

    response = whatif_agent.process_whatif(FakeContext("如果"))

    assert response.tools_called == []
    assert len(response.suggested_questions) == 3
    # 建議問句必須是可以直接點的完整問句，不是「請問您想問什麼」
    assert all(len(q) > 10 for q in response.suggested_questions)


def test_judgment_basis_caps_listed_hits():
    """判斷依據不得把所有 rule_hits 串成一坨——實測 15 條會塞爆前端欄位。"""
    from src.models import EvidenceRef, RuleHit, SensingResult
    from src.whatif_engine import MAX_LISTED_HITS, build_judgment_basis

    hits = [
        RuleHit(
            clause_id="SOP-1",
            segment_id=f"RD_TPE_{i:03d}",
            evidence=EvidenceRef(field="saturation_score", value=0.9, threshold=0.85),
            is_primary=(i == 1),
        )
        for i in range(1, 16)
    ]
    sensing = SensingResult(
        traffic_level="A",
        rule_hits=hits,
        as_of=__import__("datetime").datetime(2026, 5, 20, 22, 10),
    )

    text = build_judgment_basis(sensing, None, None, None)

    listed = [ln for ln in text.splitlines() if ln.startswith("- SOP-")]
    assert len(listed) <= MAX_LISTED_HITS + 1  # 主因 1 條 + 並行前 N 條
    assert "另有" in text
    # 不得指向決策軌跡：What-if 依 SPEC-00 §4 刻意不留痕，那裡沒有東西可看，
    # 正式週期的軌跡裡也沒有逐條 rule_hits。指路指到空地比不指路更糟。
    assert "決策軌跡" not in text


def test_clause_id_normalized_before_diff():
    """`DecisionResult.triggered_by` 用 `§2`、`RuleHit.clause_id` 用 `SOP-2`。

    不正規化就直接做集合比對，實測會回報 base=["§2"] vs new=["SOP-1"…"SOP-7"]，
    看起來像假設情境觸發了六條全新條款，其實 SOP-2 兩邊都有。
    """
    from src.whatif_engine import _normalize_clause_id

    assert _normalize_clause_id("§2") == "SOP-2"
    assert _normalize_clause_id("SOP-2") == "SOP-2"
    assert _normalize_clause_id("§ 5") == "SOP-5"
    # 認不出來的格式原樣保留，不亂猜
    assert _normalize_clause_id("未知") == "未知"


def test_tool_docstring_lists_all_supported_fields():
    """工具描述的欄位清單必須涵蓋 `supported_fields()` 的每一個欄位。

    docstring 就是 LLM 看到的工具描述。實測沒列清單時，模型會把
    `saturation_score` 縮寫成 `saturation`，`apply_scenario_overrides` 拋
    ValueError，整個 What-if 退化成「決策模組暫時不可用」。這個測試擋的是
    「以後有人加了欄位卻忘了更新描述」——那會讓同一種失敗再發生一次。
    """
    from src.agent.tools import simulate_scenario
    from src.whatif_engine import supported_fields

    # Strands @tool 會包裝函式，原始 docstring 從 __wrapped__ 或原函式取
    doc = (
        getattr(simulate_scenario, "__doc__", None)
        or getattr(getattr(simulate_scenario, "__wrapped__", None), "__doc__", "")
        or ""
    )

    missing = [
        field
        for fields in supported_fields().values()
        for field in fields
        if field not in doc
    ]
    assert not missing, f"simulate_scenario 的工具描述沒有列出這些欄位：{missing}"


def test_field_alias_maps_to_canonical_name():
    """LLM 實際用過的縮寫要能對到正規欄位名。"""
    from src.whatif_engine import TRAFFIC_FIELD_MAP

    assert TRAFFIC_FIELD_MAP["saturation"] == "saturation_score"
    assert TRAFFIC_FIELD_MAP["Saturation_Score"] == "saturation_score"


def test_unsupported_field_error_lists_legal_fields():
    """錯誤訊息要附合法欄位清單，LLM 才有辦法自我修正。"""
    from src.whatif_engine import apply_scenario_overrides, supported_fields

    class _Bundle:
        traffic = []
        crowd = []
        road_network = []

    with pytest.raises(ValueError) as exc:
        apply_scenario_overrides(_Bundle(), {"RD_TPE_004.完全不存在的欄位": 1})

    message = str(exc.value)
    for field in supported_fields()["RD_"]:
        assert field in message


@pytest.mark.parametrize(
    "question, expected",
    [
        ("如果人數到四萬，幫我出一份建議書", True),
        ("請產出報告", True),
        ("幫我生成報告", True),
        ("如果人數到四萬會怎樣？", False),
        ("這份報告怎麼算出來的？", False),  # 回溯追問，不是要產新文件
    ],
)
def test_scenario_report_intent_detection(question, expected):
    assert whatif_agent.wants_scenario_report(question) is expected
