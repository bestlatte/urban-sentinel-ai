"""系統時鐘：全系統「現在幾點」的單一來源。

為什麼需要這個模組
------------------
[2026-08-02] 這套系統同時存在兩種時間，而程式碼裡分不出來：

  **模擬器時間** —— 使用者在畫面上看到、也是所有資料被評估的那個時刻。
      時間軸從 17:00 跑到 23:30，一秒推進一分鐘。事故發生在 22:10、
      飽和度是 22:10 的飽和度、建議書講的是 22:10 的世界。

  **真實時間** —— 這台機器的牆上時鐘。Demo 當下可能是任何時候。

原本 `datetime.now()` 散落在十幾處，拿到的一律是後者。實際造成的錯誤：

  - `main.py::build_dashboard()` 用真實時間查漫遊比率（SOP-6 門檻 0.30），
    **算出來的多語通報站點數是錯的**——它查的是資料集裡另一個時段的漫遊率。
  - `trace_id` 長成 `TR-20260802-1435-0001`，而事件顯示在 22:10，
    對帳時完全串不起來。
  - 建議書落款 `generated_at`、事件解除時間、對話時間戳，全部跟畫面差好幾小時。

現在一律走 `clock.now()`：模擬器在跑就回模擬器時刻，沒在跑就回真實時間。

刻意不涵蓋的地方
----------------
兩處保持真實時間，因為它們描述的是**這個行程本身**，不是被模擬的世界：

  - `loaders.py::loaded_at` —— 資料檔是什麼時候被讀進記憶體的
  - `bedrock_status.last_ok_at` —— Bedrock 連線上一次成功是什麼時候
  - 前端 Header 的時鐘（`System Online` 旁邊）—— 那是機器在線的指示燈

依賴方向
--------
`main` 是應用層，被 `src` 反向依賴並不理想，但模擬器狀態的唯一來源就在那裡。
用函式內 import + 寬鬆的 except 包住，讓 `src` 在沒有 `main` 的情境
（單元測試直接 import 模組）照樣能跑，只是退回真實時間。
`whatif_engine.resolve_scenario_as_of()` 早就這樣做了，這裡是把同一招收斂成
一個地方，不要每個呼叫點各寫一次 try/except。
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

logger = logging.getLogger(__name__)

TZ_TAIPEI = timezone(timedelta(hours=8))


def simulation_time() -> datetime | None:
    """模擬器當前時刻；模擬器沒啟用（或取不到）回 None。"""
    try:
        from main import get_simulation_time

        return get_simulation_time()
    except Exception:  # noqa: BLE001 - 取不到只代表沒有模擬器，不是錯誤
        logger.debug("取不到模擬器時間", exc_info=True)
        return None


def now() -> datetime:
    """全系統的「現在」。模擬器在跑就是模擬器時刻，否則是真實時間。

    回傳值一律帶 tzinfo（台北 +08:00）——模擬器的時間戳來自資料集，本來就帶
    時區；真實時間這邊補上，讓兩條路徑回傳的東西可以直接互相比較與相減。
    naive datetime 混進來會在比較時拋 TypeError，而那種錯往往要到 Demo 現場
    某個特定分支被走到才會出現。
    """
    sim = simulation_time()
    if sim is not None:
        return sim if sim.tzinfo is not None else sim.replace(tzinfo=TZ_TAIPEI)
    return datetime.now(tz=TZ_TAIPEI)


def is_simulating() -> bool:
    """模擬器是否正在提供時間。給需要在措辭上區分兩者的呼叫端用。"""
    return simulation_time() is not None
