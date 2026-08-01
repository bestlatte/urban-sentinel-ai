"""部署前置檢查：把「等到 deploy 跑一半才炸」的問題全部提前到 10 秒內查完。

背景
----
`agentcore deploy` 實測踩過兩種失敗，共通點是**訊息出現得太晚、也太不明確**：

1. `CDK synth failed: node dist/bin/cdk.js: Subprocess exited with error 1`
   ——真正的原因是 `uv` 不在 PATH，但要另外手動跑一次 `node dist/bin/cdk.js`
   才看得到。CLI 吐的那行訊息完全沒提到 uv。
2. `InvalidClientTokenId` ——工作坊臨時憑證過期。這個在 Demo 現場發生時，
   會讓人以為是程式壞了。

本腳本把這些檢查前置，**每一項失敗都附上可以直接複製貼上的修復指令**。

用法
----
    python scripts/preflight.py            # 全部檢查
    python scripts/preflight.py --deploy   # 額外檢查部署專用的工具鏈
    python scripts/preflight.py --quiet    # 只在失敗時輸出（給 CI／腳本用）

回傳碼 0 = 全過，1 = 有 FAIL。WARN 不影響回傳碼。
"""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from src.env import load_env  # noqa: E402

AGENTCORE_PROJECT = Path.home() / "urban-sentinel-agentcore" / "UrbanSentinelOrch"

OK, WARN, FAIL = "ok", "warn", "fail"

_RESULTS: list[tuple[str, str, str, str]] = []
"""(status, 檢查項目, 現況, 修復指令)"""


def record(status: str, name: str, detail: str, fix: str = "") -> None:
    _RESULTS.append((status, name, detail, fix))


def _uv_bin() -> str | None:
    """找出 uv 執行檔。PATH 找不到時退回問 Python 套件要位置。

    `uv` 常常是用 `pip install uv` 裝的，執行檔會落在 `%APPDATA%\\Python\\
    Python312\\Scripts`，而那個目錄預設**不在** Windows 的 user PATH 上。
    """
    found = shutil.which("uv")
    if found:
        return found
    try:
        import uv  # noqa: PLC0415

        candidate = uv.find_uv_bin()
        return candidate if Path(candidate).exists() else None
    except Exception:
        return None


# ---------------------------------------------------------------------------
# 檢查項目
# ---------------------------------------------------------------------------


def check_env_file() -> None:
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        record(
            FAIL, ".env", "檔案不存在",
            "copy .env.example .env   然後填入設定",
        )
        return

    applied = load_env(override=False)
    record(OK, ".env", f"已載入 {len(applied)} 個變數（不覆寫既有環境變數）")


def check_region_and_model() -> None:
    from src.llm import bedrock_enabled, get_knowledge_base_id, get_model_id, get_region

    record(OK, "AWS_REGION", get_region())
    record(OK, "BEDROCK_MODEL_ID", get_model_id())
    record(OK, "USE_BEDROCK", str(bedrock_enabled()))

    kb = get_knowledge_base_id()
    if kb:
        record(OK, "KNOWLEDGE_BASE_ID", kb)
    else:
        record(OK, "KNOWLEDGE_BASE_ID", "留空 → SOP 走本機關鍵字比對（正常，非降級）")


def check_credentials() -> None:
    """憑證是否有效，以及還剩多久到期。"""
    try:
        import boto3
        from botocore.config import Config

        sts = boto3.client(
            "sts",
            region_name=os.environ.get("AWS_REGION", "us-west-2"),
            config=Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 1}),
        )
        identity = sts.get_caller_identity()
    except Exception as e:
        name = type(e).__name__
        hint = ""
        if "ExpiredToken" in str(e) or "InvalidClientTokenId" in str(e):
            hint = "憑證已過期或無效。"
        record(
            FAIL, "AWS 憑證", f"{hint}{name}: {str(e)[:120]}",
            "從工作坊入口複製新的憑證，然後執行： "
            "powershell -File scripts\\refresh_aws_creds.ps1",
        )
        return

    arn = identity["Arn"]
    record(OK, "AWS 憑證", f"{arn}（帳號 {identity['Account']}）")

    # 到期時間：臨時憑證的 token 本身不帶可讀的到期欄位，所以靠 .env 裡人工
    # 記錄的 AWS_CREDS_EXPIRE_AT（由 refresh_aws_creds.ps1 寫入）。
    expire_raw = os.environ.get("AWS_CREDS_EXPIRE_AT", "").strip()
    if not expire_raw:
        if ":assumed-role/" in arn:
            record(
                WARN, "憑證到期時間", "未記錄（這是臨時憑證，一定會過期）",
                "下次更新憑證時用 scripts\\refresh_aws_creds.ps1，它會一併記錄到期時間",
            )
        return

    try:
        expire_at = datetime.fromisoformat(expire_raw)
        if expire_at.tzinfo is None:
            expire_at = expire_at.replace(tzinfo=timezone.utc)
    except ValueError:
        record(WARN, "憑證到期時間", f"格式無法解析：{expire_raw}（需 ISO 8601）")
        return

    remaining = expire_at - datetime.now(timezone.utc)
    minutes = int(remaining.total_seconds() // 60)

    if minutes <= 0:
        record(FAIL, "憑證到期時間", f"已於 {expire_at.isoformat()} 過期",
               "powershell -File scripts\\refresh_aws_creds.ps1")
    elif minutes < 45:
        record(WARN, "憑證到期時間", f"只剩 {minutes} 分鐘（{expire_at.isoformat()}）",
               "Demo 前先更新：powershell -File scripts\\refresh_aws_creds.ps1")
    else:
        record(OK, "憑證到期時間", f"還有 {minutes // 60} 小時 {minutes % 60} 分（{expire_at.isoformat()}）")


def check_bedrock_model_access() -> None:
    """真的送一次最小的 Converse 請求——Model Access 沒開通只有這樣才驗得出來。

    [2026-08-01] 連線類錯誤會重試。這個檢查的目的是抓**設定問題**（Model Access
    沒開、model id 打錯、憑證沒權限），不是抓網路抖動——實測遇過一次
    `EndpointConnectionError` 讓整個部署被擋下，但下一秒重試就通了。
    設定錯誤（AccessDenied、ValidationException）不重試，那些重試一百次也一樣。
    """
    from src.llm import bedrock_enabled, get_model_id

    if not bedrock_enabled():
        record(OK, "Bedrock 模型存取", "USE_BEDROCK=false，略過（保底模式）")
        return

    import boto3
    from botocore.config import Config
    from botocore.exceptions import ConnectionError as BotoConnectionError
    from botocore.exceptions import ConnectTimeoutError, ReadTimeoutError

    transient = (BotoConnectionError, ConnectTimeoutError, ReadTimeoutError)
    attempts = 3
    last_error: Exception | None = None

    for attempt in range(1, attempts + 1):
        try:
            client = boto3.client(
                "bedrock-runtime",
                region_name=os.environ.get("AWS_REGION", "us-west-2"),
                config=Config(connect_timeout=5, read_timeout=20, retries={"max_attempts": 2}),
            )
            client.converse(
                modelId=get_model_id(),
                messages=[{"role": "user", "content": [{"text": "ping"}]}],
                inferenceConfig={"maxTokens": 5, "temperature": 0},
            )
        except transient as e:
            last_error = e
            if attempt < attempts:
                time.sleep(2 * attempt)
                continue
        except Exception as e:
            # 設定／權限問題：立刻報，不浪費時間重試
            record(
                FAIL, "Bedrock 模型存取", f"{type(e).__name__}: {str(e)[:150]}",
                "確認 us-west-2 的 Model Access 已開通該模型；"
                "或在 .env 改 BEDROCK_MODEL_ID（可選值見 .env.example）",
            )
            return
        else:
            suffix = f"（第 {attempt} 次嘗試才成功，網路可能不穩）" if attempt > 1 else ""
            record(OK, "Bedrock 模型存取", f"{get_model_id()} 可呼叫{suffix}")
            return

    record(
        FAIL, "Bedrock 模型存取",
        f"連線失敗 {attempts} 次：{type(last_error).__name__}: {str(last_error)[:120]}",
        "這是網路問題不是設定問題。確認網路後重跑；"
        "若 Demo 現場網路就是不穩，改用 USE_BEDROCK=false 保底模式（黃金值不受影響）",
    )


def check_golden_values() -> None:
    """本機黃金值。這是唯一不依賴 LLM 的正確性檢查，失敗代表決定性模組壞了。"""
    import asyncio

    from src import orchestrator

    previous = os.environ.get("USE_BEDROCK")
    os.environ["USE_BEDROCK"] = "false"  # 只驗決定性部分，不花 LLM 時間與費用
    try:
        orchestrator.reset()
        orchestrator.GATEWAY = orchestrator.build_gateway()
        bundle = orchestrator.GATEWAY.load_data()
        incident = next(i for i in bundle.incidents if i.event_id == "TPE_2026_ACC_001")
        result = asyncio.run(orchestrator.handle_incident(incident))
    except Exception as e:
        record(FAIL, "黃金值", f"決策週期執行失敗：{type(e).__name__}: {str(e)[:120]}")
        return
    finally:
        if previous is None:
            os.environ.pop("USE_BEDROCK", None)
        else:
            os.environ["USE_BEDROCK"] = previous

    expected = {
        "主要路線": ("RD_TPE_004", result.routes.primary.segment_id if result.routes and result.routes.primary else None),
        "次要路線": ("RD_TPE_005", result.routes.secondary.segment_id if result.routes and result.routes.secondary else None),
        "ETE 分鐘": (90, result.ete.minutes if result.ete else None),
        "恢復時間": ("2026-05-20 23:40", result.ete.recovery_at if result.ete else None),
    }
    wrong = [f"{k}: 期望 {exp}，實得 {got}" for k, (exp, got) in expected.items() if exp != got]

    if wrong:
        record(FAIL, "黃金值", "；".join(wrong))
    else:
        record(OK, "黃金值", "主 RD_TPE_004 / 次 RD_TPE_005 / ETE 90 / 恢復 2026-05-20 23:40")


def check_deploy_toolchain() -> None:
    """`--deploy` 才跑：AgentCore CLI 需要的東西。"""
    if not AGENTCORE_PROJECT.exists():
        record(
            FAIL, "AgentCore 專案", f"找不到 {AGENTCORE_PROJECT}",
            "依 加分項_AgentCore_Runtime部署.md §4 步驟 1 執行 agentcore create",
        )
    else:
        record(OK, "AgentCore 專案", str(AGENTCORE_PROJECT))

    for tool, fix in (
        ("node", "安裝 Node.js（AgentCore CDK 需要）"),
        ("agentcore", "npm install -g @aws/agentcore"),
    ):
        path = shutil.which(tool)
        if path:
            record(OK, tool, path)
        else:
            record(FAIL, tool, "找不到執行檔", fix)

    # uv：最容易踩的一個。PATH 上沒有時 CDK synth 會失敗，而 CLI 的錯誤訊息
    # 完全不會提到 uv（只說 "Subprocess exited with error 1"）。
    uv_path = _uv_bin()
    if uv_path is None:
        record(
            FAIL, "uv", "找不到（CDK synth 會失敗，且錯誤訊息不會告訴你原因）",
            "pip install uv   然後 powershell -File scripts\\fix_uv_path.ps1",
        )
    elif shutil.which("uv"):
        record(OK, "uv", uv_path)
    else:
        record(
            WARN, "uv", f"存在於 {uv_path} 但**不在 PATH 上**",
            "powershell -File scripts\\fix_uv_path.ps1"
            "（或用 scripts\\deploy_agentcore.ps1 部署，它會自動處理）",
        )


# ---------------------------------------------------------------------------
# 輸出
# ---------------------------------------------------------------------------


def report(quiet: bool) -> int:
    icons = {OK: "[ok]  ", WARN: "[warn]", FAIL: "[FAIL]"}
    failures = [r for r in _RESULTS if r[0] == FAIL]
    warnings = [r for r in _RESULTS if r[0] == WARN]

    if not quiet or failures:
        width = max(len(name) for _, name, _, _ in _RESULTS)
        print()
        for status, name, detail, _ in _RESULTS:
            if quiet and status == OK:
                continue
            print(f"{icons[status]} {name.ljust(width)}  {detail}")

    if failures or warnings:
        print("\n" + "-" * 70)
        for status, name, _, fix in failures + warnings:
            if fix:
                print(f"{icons[status]} {name} 的修復方式：\n      {fix}")

    print()
    if failures:
        print(f"結果：{len(failures)} 項失敗、{len(warnings)} 項警告 —— 不要部署，先修上面的問題。")
        return 1
    if warnings:
        print(f"結果：全部通過（{len(warnings)} 項警告）。可以部署。")
        return 0
    print("結果：全部通過。可以部署。")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deploy", action="store_true", help="額外檢查部署工具鏈（node/agentcore/uv）")
    parser.add_argument("--quiet", action="store_true", help="只輸出警告與失敗")
    args = parser.parse_args()

    check_env_file()
    check_region_and_model()
    check_credentials()
    check_bedrock_model_access()
    check_golden_values()
    if args.deploy:
        check_deploy_toolchain()

    return report(args.quiet)


if __name__ == "__main__":
    raise SystemExit(main())
