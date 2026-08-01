"""[2026-08-02] LINE 通報（Messaging API）的行為鎖定。

刻意**不打真的 LINE API**：測試不該依賴外部服務與有效憑證。
用 monkeypatch 攔住 `urllib.request.urlopen`，驗證的是我們這一側的行為
——送什麼、去重、失敗時給出什麼可執行的處置建議。
"""

from datetime import datetime, timedelta, timezone

import pytest

from src import line_notify
from src.models import (
    EteEstimate,
    Incident,
    IncidentSeverity,
    Notification,
    RouteCandidate,
    RoutePlan,
)

_TZ = timezone(timedelta(hours=8))


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    line_notify.reset_dedup()
    monkeypatch.setenv("LINE_ENABLED", "true")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "test-token")
    monkeypatch.delenv("LINE_TO_USER_ID", raising=False)


class _FakeResponse:
    status = 200

    def read(self):
        return b"{}"

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _capture(monkeypatch):
    """攔下請求，回傳一個會被填入 (url, headers, body) 的 dict。"""
    sent = {}

    def fake_urlopen(request, timeout=None):
        import json

        sent["url"] = request.full_url
        sent["headers"] = dict(request.headers)
        sent["body"] = json.loads(request.data.decode("utf-8"))
        return _FakeResponse()

    monkeypatch.setattr(line_notify.urllib.request, "urlopen", fake_urlopen)
    return sent


# --- 設定判定 ---


def test_not_configured_without_token(monkeypatch):
    monkeypatch.delenv("LINE_CHANNEL_ACCESS_TOKEN", raising=False)
    ok, reason = line_notify.is_configured()
    assert ok is False
    assert "LINE_CHANNEL_ACCESS_TOKEN" in reason


def test_disabled_flag_blocks_sending(monkeypatch):
    """Demo 現場要能一鍵關掉對外發送。"""
    monkeypatch.setenv("LINE_ENABLED", "false")
    result = line_notify.send_text("hi")
    assert result.ok is False
    assert result.mode == "disabled"


def test_disabled_send_makes_no_http_call(monkeypatch):
    monkeypatch.setenv("LINE_ENABLED", "false")

    def explode(*a, **kw):
        raise AssertionError("關閉狀態下不得發出任何請求")

    monkeypatch.setattr(line_notify.urllib.request, "urlopen", explode)
    line_notify.send_text("hi")


# --- push vs broadcast ---


def test_broadcast_when_no_user_id(monkeypatch):
    """留空 userId 就 broadcast——個人 Demo 少一個會卡住的步驟。"""
    sent = _capture(monkeypatch)
    result = line_notify.send_text("測試")

    assert result.ok and result.mode == "broadcast"
    assert sent["url"] == line_notify.BROADCAST_URL
    assert "to" not in sent["body"]
    assert sent["body"]["messages"] == [{"type": "text", "text": "測試"}]


def test_push_when_user_id_set(monkeypatch):
    monkeypatch.setenv("LINE_TO_USER_ID", "U0123456789")
    sent = _capture(monkeypatch)
    result = line_notify.send_text("測試")

    assert result.ok and result.mode == "push"
    assert sent["url"] == line_notify.PUSH_URL
    assert sent["body"]["to"] == "U0123456789"


def test_authorization_header_is_bearer_token(monkeypatch):
    sent = _capture(monkeypatch)
    line_notify.send_text("測試")
    headers = {k.lower(): v for k, v in sent["headers"].items()}
    assert headers["authorization"] == "Bearer test-token"


# --- 額度保護 ---


def test_duplicate_within_window_is_skipped(monkeypatch):
    """連點兩下、WebSocket 重連觸發重送——免費額度不該燒在重複訊息上。"""
    sent = _capture(monkeypatch)
    first = line_notify.send_text("一樣的內容")
    assert first.ok and first.mode == "broadcast"

    calls = []
    monkeypatch.setattr(
        line_notify.urllib.request, "urlopen",
        lambda *a, **kw: (calls.append(1), _FakeResponse())[1],
    )
    second = line_notify.send_text("一樣的內容")
    assert second.mode == "skipped"
    assert calls == [], "去重擋下時不得真的送出請求"


def test_force_bypasses_dedup(monkeypatch):
    _capture(monkeypatch)
    line_notify.send_text("一樣的內容")
    again = line_notify.send_text("一樣的內容", force=True)
    assert again.ok and again.mode == "broadcast"


def test_different_content_is_not_deduped(monkeypatch):
    _capture(monkeypatch)
    line_notify.send_text("內容 A")
    assert line_notify.send_text("內容 B").mode == "broadcast"


# --- 錯誤處理：永不拋例外，且要給出可執行的下一步 ---


def test_http_error_returns_actionable_diagnostics(monkeypatch):
    import urllib.error

    def fake_urlopen(request, timeout=None):
        raise urllib.error.HTTPError(
            request.full_url, 401, "Unauthorized", {},
            __import__("io").BytesIO(b'{"message":"Authentication failed"}'),
        )

    monkeypatch.setattr(line_notify.urllib.request, "urlopen", fake_urlopen)
    result = line_notify.send_text("測試")

    assert result.ok is False and result.status_code == 401
    assert result.diagnostics, "401 要告訴使用者去哪裡重新發行 token"
    assert any("token" in d.lower() for d in result.diagnostics)


def test_network_error_does_not_raise(monkeypatch):
    import urllib.error

    monkeypatch.setattr(
        line_notify.urllib.request, "urlopen",
        lambda *a, **kw: (_ for _ in ()).throw(urllib.error.URLError("no route")),
    )
    result = line_notify.send_text("測試")
    assert result.ok is False and result.mode == "error"


def test_empty_text_is_rejected_before_sending(monkeypatch):
    def explode(*a, **kw):
        raise AssertionError("空訊息不得送出")

    monkeypatch.setattr(line_notify.urllib.request, "urlopen", explode)
    assert line_notify.send_text("   ").ok is False


def test_long_text_is_truncated_not_rejected(monkeypatch):
    """超長訊息 LINE 會整則拒收，截斷比整則丟掉好。"""
    sent = _capture(monkeypatch)
    line_notify.send_text("字" * 9000)
    text = sent["body"]["messages"][0]["text"]
    assert len(text) <= line_notify.MAX_TEXT_LEN
    assert text.endswith("…")


# --- 訊息組裝 ---


def _fixture(saturated=False, no_route=False):
    incident = Incident(
        event_id="TPE_2026_ACC_001",
        type="Road_Collapse_Accident",
        location="光復南路/忠孝東路口",
        affected_segment="RD_TPE_002",
        status="Closed",
        severity=IncidentSeverity.CRITICAL,
        description="路面塌陷",
        timestamp=datetime(2026, 5, 20, 22, 10, tzinfo=_TZ),
    )
    primary = None if no_route else RouteCandidate(
        segment_id="RD_TPE_004", name="市民大道四段", eligible=True, reason_code=None,
        saturation_score=0.78, capacity_vph=2500, snapshot_at=None,
    )
    routes = RoutePlan(
        primary=primary, secondary=None, excluded=[], findings=[], candidates=[],
        no_feasible_route=no_route, all_alternatives_saturated=saturated,
    )
    ete = EteEstimate(minutes=90, recovery_at="2026-05-20 23:40",
                      formula="f", base_clearance=60, average_saturation=1.0)
    notification = Notification(zh="光復南路封閉，請改道市民大道四段。", en="Road closed.")
    return incident, notification, ete, routes


def test_message_uses_c4_notification_not_the_full_report():
    """送的是簡訊（短），不是建議書全文——後者在手機上是一整片牆。"""
    incident, notification, ete, routes = _fixture()
    msg = line_notify.build_incident_message(incident, notification, ete, routes)

    assert "光復南路封閉，請改道市民大道四段。" in msg
    assert "市民大道四段" in msg
    assert "23:40" in msg
    assert len(msg) < 300


def test_message_flags_no_substitute_in_the_header():
    """無路可替補要在標題就看得出來，不能藏在內文裡。"""
    incident, notification, ete, routes = _fixture(saturated=True)
    msg = line_notify.build_incident_message(incident, notification, ete, routes)
    assert "無可替補路段" in msg.splitlines()[0]
    assert "權宜指派" in msg


def test_message_without_any_route_tells_people_what_to_do():
    incident, notification, ete, routes = _fixture(no_route=True)
    msg = line_notify.build_incident_message(incident, notification, ete, routes)
    assert "無可行替代路線" in msg
    assert "大眾運輸" in msg


def test_message_language_selection():
    incident, notification, ete, routes = _fixture()
    msg = line_notify.build_incident_message(incident, notification, ete, routes, lang="en")
    assert "Road closed." in msg


def test_message_falls_back_to_zh_when_language_missing():
    incident, notification, ete, routes = _fixture()
    msg = line_notify.build_incident_message(incident, notification, ete, routes, lang="ko")
    assert "光復南路封閉" in msg
