"""前端 trace_id 傳遞鏈的靜態檢查。

守的是這個 bug——它是「報告書與 chatbot 給出不同建議」的根因，而且只有一行：

    api.js       async function fetchWhatIf(content, sessionId, correlationId, currentTraceId)
    chat-app.js  fetchWhatIf(text, ChatState.sessionId, ChatState.currentCorrelationId)
                                                                                    ↑ 第四個參數沒傳

`ChatState` 裡甚至沒有 `currentTraceId` 這個欄位，全 repo 沒有一行設定它。
所以後端收到的 `current_trace_id` 永遠是 null，連鎖反應：

    拿不到 incident
      → 評估時刻掉到「資料集最新時刻」（23:30）
      → 用一個跟畫面差 80 分鐘的時間掃全市
      → 路線／ETE／風險全部算在另一個世界裡

前端沒有 JS 測試框架，用靜態檢查擋住迴歸——比沒有好，而且這個 bug 的形狀
（少傳一個參數、少一個欄位）正好是靜態檢查抓得到的。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

FRONTEND_JS = Path(__file__).resolve().parents[1] / "frontend" / "js"


def _read(name: str) -> str:
    return (FRONTEND_JS / name).read_text(encoding="utf-8")


def test_chat_state_declares_current_trace_id():
    """ChatState 必須有這個欄位——它以前根本不存在。"""
    assert re.search(r"\bcurrentTraceId\s*:", _read("chat-state.js")), (
        "ChatState 少了 currentTraceId 欄位"
    )


def test_decision_completed_records_trace_id():
    """決策完成時要把 trace_id 記進 ChatState，chatbot 才知道使用者在看什麼。"""
    app = _read("app.js")
    assert "ChatState.currentTraceId = decision.trace_id" in app, (
        "onDecisionCompleted 沒有把 trace_id 交給 ChatState"
    )


def test_trace_id_is_recorded_before_dedup_guard():
    """必須寫在去重檢查**之前**。

    REST 回應與 WS 推播會各觸發一次 `onDecisionCompleted`，第二次會被
    `_processedTraceIds` 擋掉。寫在去重之後就有一半機率設不到值——
    那種「有時候對有時候錯」的 bug 最難查。
    """
    app = _read("app.js")
    assign = app.index("ChatState.currentTraceId = decision.trace_id")
    dedup = app.index("_processedTraceIds.has(decision.trace_id)")
    assert assign < dedup, "trace_id 的賦值被排在去重檢查之後"


def test_send_message_passes_trace_id_to_api():
    """sendMessage 必須把第四個參數傳出去——漏掉它就是整個 bug 的起點。"""
    chat_app = _read("chat-app.js")
    call = re.search(r"fetchWhatIf\((.*?)\)", chat_app, re.S)
    assert call, "找不到 fetchWhatIf 呼叫"
    assert "ChatState.currentTraceId" in call.group(1), (
        "fetchWhatIf 沒有收到 currentTraceId，後端會一直拿到 null"
    )


def test_api_signature_still_expects_four_args():
    """api.js 的簽章沒變的話，上面那條檢查才有意義。"""
    api = _read("api.js")
    assert re.search(
        r"function\s+fetchWhatIf\s*\(\s*content\s*,\s*sessionId\s*,\s*correlationId\s*,\s*currentTraceId\s*\)",
        api,
    ), "fetchWhatIf 簽章改了，請同步更新本測試與呼叫端"


@pytest.mark.parametrize("banned", ["命中條款", "collapse_after", "relation_counts", "total_hits"])
def test_hit_clause_ui_stays_removed(banned):
    """「命中條款」那套 UI 不得復活。

    使用者的要求是「確保不要再有命中條款」。這裡擋的是有人日後把摺疊清單
    或計數欄位加回推理鏈——那會讓同一個抱怨再發生一次。
    """
    chain = _read("reasoning-chain.js")
    # 註解裡說明歷史沿革是可以的，只擋實際會渲染出來的字串與欄位存取
    code = re.sub(r"/\*.*?\*/", "", chain, flags=re.S)
    code = re.sub(r"^\s*//.*$", "", code, flags=re.M)
    assert banned not in code, f"推理鏈的程式碼裡又出現了 {banned}"
