"""送一則測試訊息到 LINE，驗證 Messaging API 憑證是否設定正確。

用法：
    python -m scripts.send_line_test
    python -m scripts.send_line_test "自訂訊息內容"

刻意做成獨立腳本而不是只靠 UI 按鈕：設定 LINE 憑證時會踩的坑（token 貼錯、
用到 LINE Login channel、忘了加官方帳號好友）全都跟決策流程無關，
在這裡兩秒就能試一次，不必先注入事件、等建議書生成完才知道 token 是壞的。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.env import load_env  # noqa: E402

load_env()

from src import line_notify  # noqa: E402


def main() -> int:
    message = " ".join(sys.argv[1:]).strip() or (
        "【測試】城市應變分析系統 LINE 通報連線正常。\n"
        "收到這則訊息代表 Channel access token 與好友關係都設定完成。"
    )

    ok, reason = line_notify.is_configured()
    print(f"設定狀態：{reason}")
    if not ok:
        print("\n請先完成設定，步驟見 README「LINE 通報設定」。")
        return 1

    import os

    to_user = os.getenv("LINE_TO_USER_ID", "").strip()
    print(f"發送模式：{'push（指定 userId）' if to_user else 'broadcast（官方帳號所有好友）'}")
    print(f"訊息內容：\n{message}\n")

    result = line_notify.send_text(message, force=True)

    if result.ok:
        print(f"✓ 已送出（{result.mode}）。請檢查手機 LINE。")
        return 0

    print(f"✗ 發送失敗：{result.detail}")
    for line in result.diagnostics:
        print(f"  → {line}")
    if not result.diagnostics:
        print("  → 若持續失敗，請確認 token 是 Messaging API channel 的 long-lived token，")
        print("    且已用手機掃描 QR code 將該官方帳號加為好友。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
