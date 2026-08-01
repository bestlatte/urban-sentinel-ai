"""LINE 通報：把 C4 產出的多語通報實際送到 LINE。

為什麼是 Messaging API 而不是 LINE Notify
------------------------------------------
**LINE Notify 已於 2025-03-31 終止服務**。網路上多數「一行 curl 發 LINE」的
教學都是那套，現在全部失效。唯一可用的是 LINE Messaging API（官方帳號）。

為什麼不需要 webhook / ngrok
----------------------------
`push` 與 `broadcast` 都是**我們主動打出去**的 HTTPS 請求，LINE 不需要回連。
webhook 只有在「要接收使用者傳給官方帳號的訊息」時才需要——本專案是單向通報，
所以不必把本機服務暴露到公網。

為什麼用 urllib 而不是 requests
--------------------------------
`requests` 目前只是 boto3／strands 的傳遞相依，沒有宣告在 `pyproject.toml` 裡。
這裡要做的事情就是一個帶 header 的 JSON POST，stdlib 綽綽有餘。同樣的判斷
`src/env.py` 也做過一次（沒有為了讀 `.env` 引入 python-dotenv）。

設定
----
`.env` 三個鍵（取得方式見 README「LINE 通報設定」）：

    LINE_CHANNEL_ACCESS_TOKEN=...   # 必要。Messaging API 分頁發行的長期 token
    LINE_TO_USER_ID=Uxxxxxxxx...    # 選填。留空則改用 broadcast（送給所有好友）
    LINE_ENABLED=true               # 選填。false 時一律不送，供 Demo 現場快速關閉

刻意讓 `LINE_TO_USER_ID` 可以留空：個人 Demo 時官方帳號通常只有你一個好友，
broadcast 不必先查 userId 就能送到，少一個會卡住的步驟。
"""

from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from src import clock

logger = logging.getLogger(__name__)

PUSH_URL = "https://api.line.me/v2/bot/message/push"
BROADCAST_URL = "https://api.line.me/v2/bot/message/broadcast"

MAX_TEXT_LEN = 4900
"""LINE 單則文字訊息上限 5000 字，留一點餘裕給截斷標記。

交控建議書全文會超過，所以送出去的是 C4 通報（簡訊用，本來就短），
不是建議書本身。
"""

_TIMEOUT_S = 10.0
"""外部 HTTP 呼叫的逾時。指揮台按下按鈕後不該等超過這個時間——
送不出去要立刻知道，而不是畫面卡住。"""

_DEDUP_WINDOW = timedelta(seconds=60)
"""同一則內容在這個時間內不重送。

免費方案每月訊息則數有上限，而「連點兩下送出」「WebSocket 重連觸發重送」
這種事在 Demo 現場一定會發生。把額度燒在重複訊息上是最不值得的。
"""

_recent_sends: dict[str, datetime] = {}
"""內容指紋 → 上次送出時間。行程內記憶體，重啟即清空（可接受）。"""


@dataclass
class LineSendResult:
    """送出結果。**永遠回傳結果物件，不拋例外**——通報失敗不該讓決策週期中斷。"""

    ok: bool
    mode: str
    """`push` / `broadcast` / `disabled` / `skipped`（去重擋下）/ `error`。"""
    detail: str = ""
    status_code: int | None = None
    sent_text: str = ""
    sent_at: str | None = None
    diagnostics: list[str] = field(default_factory=list)
    """設定或憑證有問題時，給出**可以直接照做**的下一步，而不是丟原始錯誤碼。"""


def is_configured() -> tuple[bool, str]:
    """有沒有辦法送？回傳 (可用, 原因)。原因是給人看的，會直接顯示在畫面上。"""
    if os.getenv("LINE_ENABLED", "true").strip().lower() == "false":
        return False, "LINE 通報已由 LINE_ENABLED=false 關閉"
    if not os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip():
        return False, "尚未設定 LINE_CHANNEL_ACCESS_TOKEN（見 README「LINE 通報設定」）"
    return True, "已設定"


def _fingerprint(text: str, target: str) -> str:
    return f"{target}::{text}"


def _diagnose(status: int, body: str) -> list[str]:
    """把 LINE 的錯誤碼翻成「你現在該去做什麼」。

    這幾種是實際設定過程中一定會遇到的，直接寫成處置步驟比貼原始訊息有用——
    401 與 403 長得很像但要做的事完全不同。
    """
    if status == 401:
        return [
            "Channel access token 無效或已失效。",
            "到 LINE Developers Console → 你的 Messaging API channel → Messaging API 分頁，"
            "重新發行 long-lived channel access token，貼回 .env 的 LINE_CHANNEL_ACCESS_TOKEN。",
        ]
    if status == 403:
        return [
            "token 有效，但這個官方帳號沒有推送權限。",
            "常見原因：用到了 LINE Login channel 的 token（要用 Messaging API channel 的）。",
        ]
    if status == 400 and "Invalid to" in body:
        return [
            "LINE_TO_USER_ID 不是合法的 userId。",
            "它是 U 開頭的 33 字元字串，在 Console 的 Basic settings 分頁最下方「Your user ID」。",
            "不確定就把 LINE_TO_USER_ID 留空，系統會改用 broadcast 送給所有好友。",
        ]
    if status == 400 and "not found" in body.lower():
        return [
            "找不到收件對象——通常是**還沒把官方帳號加為好友**。",
            "到 Messaging API 分頁掃描 QR code 加好友後再試一次。",
        ]
    if status == 429:
        return [
            "已達免費方案的每月訊息額度或短時間內請求過多。",
            "到 LINE Official Account Manager 確認本月用量。",
        ]
    return []


def send_text(text: str, *, force: bool = False) -> LineSendResult:
    """送一則純文字到 LINE。

    設定了 `LINE_TO_USER_ID` 就 push 給那個人，否則 broadcast 給所有好友。

    Args:
        text: 訊息內容，超過 `MAX_TEXT_LEN` 會被截斷（LINE 會整則拒收，不截反而更糟）
        force: 略過去重窗口。使用者手動按「重送」時用。
    """
    enabled, reason = is_configured()
    if not enabled:
        logger.info("LINE 通報未送出：%s", reason)
        return LineSendResult(ok=False, mode="disabled", detail=reason)

    body_text = (text or "").strip()
    if not body_text:
        return LineSendResult(ok=False, mode="error", detail="訊息內容為空，未送出")

    if len(body_text) > MAX_TEXT_LEN:
        body_text = body_text[: MAX_TEXT_LEN - 1] + "…"

    token = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "").strip()
    to_user = os.getenv("LINE_TO_USER_ID", "").strip()

    if to_user:
        url, payload, mode = PUSH_URL, {"to": to_user, "messages": []}, "push"
    else:
        url, payload, mode = BROADCAST_URL, {"messages": []}, "broadcast"
    payload["messages"] = [{"type": "text", "text": body_text}]

    # 去重：同樣的內容、同樣的對象，一分鐘內只送一次
    key = _fingerprint(body_text, to_user or "*broadcast*")
    now = clock.now()
    if not force:
        last = _recent_sends.get(key)
        if last is not None and now - last < _DEDUP_WINDOW:
            logger.info("LINE 通報略過（%s 秒內已送過相同內容）", int(_DEDUP_WINDOW.total_seconds()))
            return LineSendResult(
                ok=True, mode="skipped", sent_text=body_text,
                detail="相同內容剛送出過，未重複發送（避免消耗免費額度）",
            )

    request = urllib.request.Request(
        url,
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {token}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_S) as resp:
            status = resp.status
            resp.read()
    except urllib.error.HTTPError as e:
        detail = e.read().decode("utf-8", errors="replace")[:400]
        # token 絕不進日誌——這個檔案的錯誤訊息會被直接顯示在畫面上
        logger.warning("LINE 通報失敗（HTTP %s）：%s", e.code, detail)
        return LineSendResult(
            ok=False, mode="error", status_code=e.code,
            detail=f"LINE API 回應 {e.code}：{detail}",
            sent_text=body_text,
            diagnostics=_diagnose(e.code, detail),
        )
    except urllib.error.URLError as e:
        logger.warning("LINE 通報連線失敗：%s", e.reason)
        return LineSendResult(
            ok=False, mode="error", detail=f"連線 LINE API 失敗：{e.reason}",
            sent_text=body_text,
            diagnostics=["確認這台機器可以連外，且沒有被 proxy 或防火牆擋住 api.line.me。"],
        )
    except Exception as e:  # noqa: BLE001 - 通報失敗永遠不該讓呼叫端炸掉
        logger.exception("LINE 通報發生未預期錯誤")
        return LineSendResult(ok=False, mode="error", detail=f"未預期錯誤：{e}", sent_text=body_text)

    _recent_sends[key] = now
    logger.info("LINE 通報已送出（%s，%d 字）", mode, len(body_text))
    return LineSendResult(
        ok=True, mode=mode, status_code=status,
        detail="已送出", sent_text=body_text, sent_at=now.isoformat(),
    )


_LANG_LABEL = {"zh": "中文", "en": "English", "ja": "日本語", "ko": "한국어"}


def build_incident_message(incident, notification, ete=None, routes=None, lang: str = "zh") -> str:
    """把決策結果組成一則適合 LINE 的通報。

    以 C4 的多語通報為主體——那本來就是為了「發給民眾的簡訊」而生成的，
    長度與語氣都對。前後補上事件與恢復時間，讓收訊者不必回頭查儀表板。

    刻意**不送**交控建議書全文：那是給指揮官看的內部文件，好幾百字，
    在手機上是一整片牆。
    """
    lines: list[str] = []

    location = getattr(incident, "location", None) or ""
    header = "【交通通報】"
    if routes is not None and (
        getattr(routes, "no_feasible_route", False)
        or getattr(routes, "all_alternatives_saturated", False)
    ):
        header = "【⚠️ 交通通報・無可替補路段】"
    lines.append(f"{header}{location}")

    body = ""
    if notification is not None:
        body = getattr(notification, lang, None) or getattr(notification, "zh", "") or ""
    if body:
        lines.append("")
        lines.append(body)

    detail: list[str] = []
    if routes is not None:
        primary = getattr(routes, "primary", None)
        if primary is not None:
            note = "（仍壅塞，權宜指派）" if getattr(routes, "all_alternatives_saturated", False) else ""
            detail.append(f"建議改道：{primary.name}{note}")
        elif getattr(routes, "no_feasible_route", False):
            detail.append("目前無可行替代路線，請依現場指揮或改乘大眾運輸")
    if ete is not None:
        detail.append(f"預計恢復：{ete.recovery_at}（約 {ete.minutes} 分鐘）")

    if detail:
        lines.append("")
        lines.extend(detail)

    if lang != "zh":
        lines.append("")
        lines.append(f"（{_LANG_LABEL.get(lang, lang)}）")

    return "\n".join(lines).strip()


def reset_dedup() -> None:
    """測試輔助：清空去重快取。"""
    _recent_sends.clear()
