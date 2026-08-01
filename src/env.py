"""`.env` 載入器（零依賴，取代 python-dotenv）。

為什麼需要這個檔案
------------------
`.env.example` 從專案開始就存在，但**全 repo 沒有任何一行程式讀它**（零
`load_dotenv`、零 `python-dotenv` 依賴）。所有設定都是 `os.getenv()` 直接讀
行程環境變數，所以把值寫進 `.env` 一直是完全沒有作用的——這個檔案在此之前
是一份文件，不是一個機制。

為什麼不用 python-dotenv
------------------------
`00-tech-stack.md` §1 是固定技術棧，加依賴要有充分理由。這裡要做的事情
（讀檔、去註解、拆 KEY=VALUE、去引號）不到 40 行，不值得為它多一個套件、
多一份 AgentCore 部署包的相依。

為什麼不用 `source .env`
------------------------
主要開發環境是 PowerShell，`source`／`.` 不存在。就算在 Git Bash 裡 source，
目前 `.env` 混用了兩種寫法：

    AWS_REGION=us-west-2                  ← 沒有 export，只是 shell 區域變數
    export AWS_ACCESS_KEY_ID="ASIA..."    ← 有 export，才會傳給子行程

`source` 之後只有帶 `export` 的那幾行會傳進 Python，`AWS_REGION`、`USE_BEDROCK`
這些**完全不會生效**，而且沒有任何錯誤訊息——是那種會讓人查半天的失敗。
本載入器兩種寫法都認（`export ` 前綴會被剝掉）。

使用方式
--------
在行程進入點最早的地方呼叫一次：

    from src.env import load_env
    load_env()

已存在的環境變數**不會被覆寫**（`override=False` 預設）。這樣 CI、容器、
AgentCore Runtime 注入的值一律優先於本機 `.env`，符合十二要素應用的慣例。
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_ENV_PATH = Path(__file__).resolve().parents[1] / ".env"


def parse_env_text(text: str) -> dict[str, str]:
    """把 `.env` 內容解析成 dict。不碰 `os.environ`，方便單獨測試。

    支援：`KEY=VALUE`、`export KEY=VALUE`、單/雙引號包住的值、`#` 開頭的整行註解、
    空行。**不支援**變數展開（`$OTHER`）與多行值——本專案用不到，而且支援它們
    就得處理跳脫規則，那才是真的該換 python-dotenv 的時候。
    """
    result: dict[str, str] = {}

    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        if line.startswith("export "):
            line = line[len("export ") :].lstrip()

        if "=" not in line:
            continue

        key, _, value = line.partition("=")
        key = key.strip()
        if not key:
            continue

        value = value.strip()
        # 去掉成對的引號。只去成對的——值裡面本來就有單邊引號時不該被吃掉。
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]

        result[key] = value

    return result


def load_env(path: str | Path | None = None, override: bool = False) -> dict[str, str]:
    """讀取 `.env` 並寫進 `os.environ`。回傳實際套用的鍵值。

    Args:
        path: `.env` 路徑，預設是 repo 根目錄的 `.env`
        override: True 時覆寫已存在的環境變數。預設 False——外部注入的值優先。

    檔案不存在時安靜略過（回空 dict）。這是正常情況，不是錯誤：CI 與
    AgentCore Runtime 都不會有 `.env`，那裡的設定由平台注入。
    """
    env_path = Path(path) if path is not None else DEFAULT_ENV_PATH

    if not env_path.exists():
        logger.debug("找不到 %s，略過載入", env_path)
        return {}

    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError as e:
        logger.warning("讀取 %s 失敗：%s", env_path, e)
        return {}

    applied: dict[str, str] = {}
    for key, value in parse_env_text(text).items():
        if not override and key in os.environ:
            continue
        os.environ[key] = value
        applied[key] = value

    if applied:
        # 只印 key，不印 value——`.env` 裡有 AWS_SECRET_ACCESS_KEY 與
        # AWS_SESSION_TOKEN，印出來就等於把憑證寫進日誌檔。
        logger.info("已從 %s 載入 %d 個環境變數：%s",
                    env_path, len(applied), ", ".join(sorted(applied)))

    return applied
