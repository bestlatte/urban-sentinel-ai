"""`src/bedrock_status` 的回歸測試。

這個模組存在的理由是一個具體缺陷：在此之前，全系統判斷「Bedrock 能不能用」
只靠 `USE_BEDROCK` 環境變數，而那是「**允不允許**呼叫」的旗標，不是「呼叫
**通不通**」。憑證失效時 `/api/health` 照樣回 `use_bedrock: true`、Dashboard KPI
照樣顯示 Live，只有建議書安靜地退成模板版——Demo 現場幾乎不可能當場察覺。
"""

from __future__ import annotations

import os

import pytest

os.environ.setdefault("USE_BEDROCK", "false")

from src import bedrock_status


@pytest.fixture(autouse=True)
def clean_state():
    bedrock_status.reset()
    yield
    bedrock_status.reset()


def test_initial_mode_is_unknown_not_live(monkeypatch):
    """剛啟動、還沒驗證時必須是 unknown。

    這是整個模組的核心主張：「還沒驗證」歸進 live 就是原本那個 bug（樂觀假設
    然後騙人），歸進 degraded 又會讓剛啟動的系統看起來壞掉。第三態是必要的。
    """
    monkeypatch.setenv("USE_BEDROCK", "true")
    status = bedrock_status.get_status()

    assert status["reachable"] is None
    assert status["mode"] == "unknown"
    assert status["mode"] != "live"


def test_flag_true_does_not_imply_live(monkeypatch):
    """USE_BEDROCK=true 本身不足以宣稱 live——這正是原本的錯誤推論。"""
    monkeypatch.setenv("USE_BEDROCK", "true")

    assert bedrock_status.get_status()["enabled"] is True
    assert bedrock_status.get_status()["mode"] == "unknown"

    bedrock_status.record_success("test-model", 120)
    assert bedrock_status.get_status()["mode"] == "live"


def test_use_bedrock_false_is_degraded_not_unknown(monkeypatch):
    """保底模式是明確的降級，不是「不知道」。"""
    monkeypatch.setenv("USE_BEDROCK", "false")
    status = bedrock_status.get_status()

    assert status["mode"] == "degraded"
    assert "保底模式" in status["message"]


def test_active_model_id_records_what_was_actually_used(monkeypatch):
    """`active_model_id` 記的是實際送出的模型，不是設定檔寫的。

    這是「我到底在用哪個模型」唯一可信的答案——C1-C4 走 Haiku、A2/W1 走 Sonnet，
    只看設定值會以為全系統只用一個模型。
    """
    monkeypatch.setenv("USE_BEDROCK", "true")
    monkeypatch.setenv("BEDROCK_MODEL_ID", "設定檔寫的模型")

    bedrock_status.record_success("實際用的模型", 88)
    status = bedrock_status.get_status()

    assert status["configured_model_id"] == "設定檔寫的模型"
    assert status["active_model_id"] == "實際用的模型"
    assert status["last_latency_ms"] == 88


@pytest.mark.parametrize(
    "exc,expected_kind",
    [
        (Exception("ExpiredToken: The security token included in the request is expired"), "credential"),
        (Exception("UnrecognizedClientException: The security token is invalid"), "credential"),
        (Exception("AccessDeniedException: not authorized to perform bedrock:InvokeModel"), "credential"),
        (Exception("ResourceNotFoundException: model not found"), "model"),
        (Exception("This model version has reached the end of its life"), "model"),
        (TimeoutError("Converse(x) 逾時（>30s）"), "network"),
        (Exception("Connection reset by peer"), "network"),
    ],
)
def test_error_classification(monkeypatch, exc, expected_kind):
    """錯誤要分類，橫幅才講得出可行動的話。

    「憑證失效請更新」跟「連線不穩」對值班人員是完全不同的指示；
    一律顯示「LLM 不可用」等於沒說。

    網路類要送滿容忍次數才會寫進 `last_error_kind`（見下面的容忍度測試）。
    """
    monkeypatch.setenv("USE_BEDROCK", "true")
    for _ in range(bedrock_status.NETWORK_FAILURE_TOLERANCE):
        bedrock_status.record_failure(exc)

    assert bedrock_status.get_status()["last_error_kind"] == expected_kind


def test_single_network_blip_does_not_flip_to_degraded(monkeypatch):
    """單次瞬斷不得讓狀態翻紅。

    實測跑一輪決策週期時，M4B 解釋鏈遇到一次
    `Connection was closed before we received a valid response`，下一次呼叫立刻
    就成功。若一次就翻紅，Demo 現場的橫幅會閃一下再自己恢復——看起來像系統不穩，
    其實只是一個封包。
    """
    monkeypatch.setenv("USE_BEDROCK", "true")
    bedrock_status.record_success("m1")

    bedrock_status.record_failure(Exception("Connection was closed before we received a valid response"))

    status = bedrock_status.get_status()
    assert status["mode"] == "live", "單次網路瞬斷不該判定降級"
    assert status["failure_count"] == 1, "但失敗次數仍要如實記錄"


def test_consecutive_network_failures_do_flip(monkeypatch):
    """連續失敗就不是抖動了，該翻。"""
    monkeypatch.setenv("USE_BEDROCK", "true")
    bedrock_status.record_success("m1")

    for _ in range(bedrock_status.NETWORK_FAILURE_TOLERANCE):
        bedrock_status.record_failure(Exception("Connection reset by peer"))

    assert bedrock_status.get_status()["mode"] == "degraded"


def test_credential_error_flips_immediately(monkeypatch):
    """憑證錯誤不會自己好，等第二次只是延後通知。"""
    monkeypatch.setenv("USE_BEDROCK", "true")
    bedrock_status.record_success("m1")

    bedrock_status.record_failure(Exception("ExpiredToken: expired"))

    assert bedrock_status.get_status()["mode"] == "degraded"


def test_success_resets_consecutive_counter(monkeypatch):
    """成功之後計數歸零，否則整場 Demo 累積的零星失敗最後會誤觸降級。"""
    monkeypatch.setenv("USE_BEDROCK", "true")

    bedrock_status.record_failure(Exception("Connection reset"))
    bedrock_status.record_success("m1")
    bedrock_status.record_failure(Exception("Connection reset"))

    assert bedrock_status.get_status()["mode"] == "live"


def test_credential_error_message_is_actionable(monkeypatch):
    monkeypatch.setenv("USE_BEDROCK", "true")
    bedrock_status.record_failure(Exception("ExpiredToken: expired"))

    message = bedrock_status.get_status()["message"]
    assert "憑證" in message
    assert "更新" in message


def test_recovery_flips_back_to_live(monkeypatch):
    """壞掉之後恢復要能翻回來——Demo 中途換憑證重試就是這個情境。"""
    monkeypatch.setenv("USE_BEDROCK", "true")

    bedrock_status.record_failure(Exception("ExpiredToken"))
    assert bedrock_status.get_status()["mode"] == "degraded"

    bedrock_status.record_success("model-x")
    status = bedrock_status.get_status()
    assert status["mode"] == "live"
    assert status["last_error"] is None
    assert status["last_error_kind"] is None


def test_probe_skips_request_when_disabled(monkeypatch):
    """USE_BEDROCK=false 時不得真的送出請求（00-tech-stack.md §6）。"""
    monkeypatch.setenv("USE_BEDROCK", "false")

    called = []

    def _boom(*args, **kwargs):
        called.append(1)
        raise AssertionError("保底模式下不該送出 Bedrock 請求")

    monkeypatch.setattr("src.llm.invoke_converse", _boom)

    assert bedrock_status.probe() is False
    assert called == []


# 下面兩個探測測試刻意攔 `llm.run_with_timeout`（真正送出請求的那一層）而不是
# `llm.invoke_converse`。因為狀態記錄就發生在 `invoke_converse` 內部——攔掉它
# 等於連要驗的行為一起攔掉，測試會通過但真實情境沒被涵蓋。


def test_probe_records_failure_without_raising(monkeypatch):
    """探測失敗是預期情境之一，不得往上拋炸掉啟動流程。"""
    monkeypatch.setenv("USE_BEDROCK", "true")

    from src import llm

    def _fail(fn, timeout_s, label=""):
        raise Exception("ExpiredToken: nope")

    monkeypatch.setattr(llm, "run_with_timeout", _fail)

    assert bedrock_status.probe() is False
    status = bedrock_status.get_status()
    assert status["mode"] == "degraded"
    assert status["last_error_kind"] == "credential"


def test_probe_success_marks_live(monkeypatch):
    monkeypatch.setenv("USE_BEDROCK", "true")

    from src import llm

    monkeypatch.setattr(llm, "run_with_timeout", lambda fn, t, label="": "OK")

    assert bedrock_status.probe() is True
    assert bedrock_status.get_status()["mode"] == "live"


def test_probe_does_not_double_count(monkeypatch):
    """探測只算一次成功。

    回歸測試：`probe()` 原本自己也呼叫 `record_success`，而 `invoke_converse`
    內部已經記過一次——啟動後 `/api/health` 的 `success_count` 是 2，
    統計就不再是「真實呼叫次數」。
    """
    monkeypatch.setenv("USE_BEDROCK", "true")

    from src import llm

    monkeypatch.setattr(llm, "run_with_timeout", lambda fn, t, label="": "OK")

    bedrock_status.probe()

    assert bedrock_status.get_status()["success_count"] == 1


def test_invoke_converse_reports_failure_to_status(monkeypatch):
    """真實呼叫路徑要把成敗回報進來——狀態由真實流量驅動，不另開輪詢。"""
    monkeypatch.setenv("USE_BEDROCK", "true")

    from src import llm

    def _fail_call(fn, timeout_s, label=""):
        raise Exception("ExpiredToken: expired")

    monkeypatch.setattr(llm, "run_with_timeout", _fail_call)

    with pytest.raises(Exception):
        llm.invoke_converse("sys", "msg", model_id="m1")

    assert bedrock_status.get_status()["last_error_kind"] == "credential"


def test_invoke_converse_reports_success_to_status(monkeypatch):
    monkeypatch.setenv("USE_BEDROCK", "true")

    from src import llm

    monkeypatch.setattr(llm, "run_with_timeout", lambda fn, t, label="": "生成結果")

    assert llm.invoke_converse("sys", "msg", model_id="haiku-x") == "生成結果"

    status = bedrock_status.get_status()
    assert status["mode"] == "live"
    assert status["active_model_id"] == "haiku-x"
