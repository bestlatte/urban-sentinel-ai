"""FastAPI 入口：四個 REST 端點 + /ws + 掛載 frontend/ 靜態檔（單一 Server）。

參考 spec：`.kiro/specs/m5-api-orchestrator-dashboard/design.md` 第3節「main.py：端點與payload對應」；
固定 API 表面見 `.kiro/steering/00-tech-stack.md` §4，**不得擴充端點**。

`POST /api/what-if` 依問題類型回傳 `WhatIfResult` 或 `TraceAnswer`，見
`.kiro/steering/04-system-architecture.md` §5 三分支路由規則，不要誤以為這個
端點永遠回傳同一種形狀。
"""

from __future__ import annotations



import contextlib
import logging
import os
from datetime import datetime, timezone, timedelta

# [2026-08-01] 設定日誌，否則本檔與 `src/*` 的 `logger.info()` **一行都不會出現**。
#
# 實測：Python 根 logger 預設等級是 WARNING，而 uvicorn 只設定它自己的
# `uvicorn.*` logger。所以在此之前，所有 `logger.info(...)` 都是寫給空氣看的——
# 包含「Bedrock 探測成功：model=…」這種 Demo 前最需要確認的訊息。
# `logger.warning` 以上因為超過根 logger 門檻才碰巧看得到。
#
# 只把自己的模組拉到 INFO，第三方留在 WARNING：botocore/urllib3 的 INFO 會把
# 每次 HTTP 請求都印出來，Demo 現場的主控台會被洗版，真正重要的訊息反而看不見。
logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logging.getLogger("src").setLevel(logging.INFO)
logging.getLogger(__name__).setLevel(logging.INFO)

logger = logging.getLogger(__name__)

# [2026-08-01] `.env` 載入必須在**所有其他 import 之前**。
# 有些模組會在 import 時就讀環境變數（例如 `bedrock_service/sop_data.py` 讀檔、
# 早期版本的 `sop_retriever.USE_BEDROCK` 讀旗標），晚一步載入這些值就已經固化成
# 錯的了。在此之前全 repo 沒有任何一行讀 `.env`——寫進去的值一直是沒有作用的，
# 見 `src/env.py` 的說明。
from src.env import load_env  # noqa: E402

load_env()

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from src import clock, orchestrator  # noqa: E402
from src.ws_manager import ConnectionManager  # noqa: E402

app = FastAPI()
ws_manager = ConnectionManager()

# [2026-07-28總架構師補充：架構完整性修正] 原本這裡寫 `GATEWAY = build_gateway()`
# 建立的是 main.py 自己的區域變數，跟 `src/orchestrator.py` 模組層級的 `GATEWAY`
# （orchestrator.py 內的函式實際讀取的那個）是兩個不同的名字空間——orchestrator.py
# 的 handle_incident/handle_trigger_batch 永遠只會看到 None。改成直接賦值給
# orchestrator 模組本身，確保只有一份 GATEWAY 實例。
orchestrator.GATEWAY = orchestrator.build_gateway()


@app.on_event("startup")
async def _register_main_loop():
    """把主 event loop 登記給 `src/async_bridge`。

    決策週期與 W1 對話現在都跑在工作執行緒（`asyncio.to_thread`），那些執行緒
    裡的同步程式碼要推 WebSocket 訊息時，需要一個明確的 loop 參照才送得出去。
    必須在任何請求進來之前登記，所以放在 startup。
    """
    from src.async_bridge import set_main_loop
    from src import bedrock_status

    set_main_loop()
    bedrock_status.set_broadcaster(ws_manager.broadcast)


@app.on_event("startup")
async def _probe_bedrock():
    """啟動時真的呼叫一次 Bedrock，確認「現在到底通不通」。

    為什麼要探測而不是讀旗標
    ------------------------
    `USE_BEDROCK=true` 說的是「**允許**呼叫」，不是「呼叫**通得了**」。兩者分歧時
    （憑證失效、金鑰停用、模型下架、斷網），系統原本會一路顯示正常，只有建議書
    安靜地退成模板版——Demo 現場幾乎不可能當場察覺。

    探測用 `max_tokens=1`，成本可忽略，但驗到的東西跟完整呼叫一樣多：憑證有效、
    有 InvokeModel 權限、模型 ID 存在且已開通。

    放在 `to_thread`：boto3 是同步的，直接 await 會擋住其他 startup handler
    與第一批請求。探測失敗不影響啟動——保底模式本來就該能跑。
    """
    import asyncio

    from src import bedrock_status

    try:
        await asyncio.to_thread(bedrock_status.probe)
        status = bedrock_status.get_status()
    except Exception as e:
        logger.warning(f"Bedrock 啟動探測異常（不影響啟動）: {e}")
        return

    _print_startup_banner(status)


def _print_startup_banner(status: dict) -> None:
    """把 Bedrock 實況印成一眼看得懂的區塊。

    用 `print` 而不是 `logger`：這是**給人在 Demo 前確認的**，不是給日誌收集器的。
    它必須在終端機上明顯到不可能錯過——「我這次到底有沒有在用 Bedrock 模型」
    是每次 Demo 前都要回答的問題，答案不該埋在一行 INFO 裡跟其他訊息混在一起。
    """
    mode = status["mode"]
    marks = {"live": "[OK]", "degraded": "[!!]", "unknown": "[??]"}
    line = "=" * 62

    print(line)
    print(f"  {marks.get(mode, '[??]')}  系統模式：{mode.upper()}")
    print(f"       {status['message']}")
    if mode == "live":
        print(f"       模型　：{status['active_model_id']}")
        print(f"       建議書：{status['configured_report_model_id']}")
        print(f"       區域　：{status['region']}　延遲：{status['last_latency_ms']}ms")
    else:
        print(f"       設定的模型：{status['configured_model_id']}")
        if status["last_error"]:
            print(f"       錯誤　：{status['last_error'][:150]}")
        print("       決定性模組（規則／路網／ETE）不受影響，黃金值照常")
    print(line)


@app.on_event("startup")
async def _startup_rule_scan():
    """啟動時跑一次全量規則評估，觸發 handle_trigger_batch。"""
    global _last_traffic_level
    try:
        bundle = orchestrator.GATEWAY.load_data()
        sensing = orchestrator.GATEWAY.evaluate_rules(bundle, incident=None)

        # 推播 rules.evaluated.v1（每次規則評估後都推，讓 F1 即時更新）
        await ws_manager.broadcast({
            "message_type": "rules.evaluated.v1",
            "payload": sensing.model_dump(mode="json"),
        })

        # 找出命中的 SOP 條款，組成 batch
        triggered = []
        seen_sections = set()
        for hit in sensing.rule_hits:
            section = hit.clause_id.replace("SOP-", "")
            if section not in seen_sections:
                seen_sections.add(section)
                triggered.append({"section": int(section), "clause_id": hit.clause_id})
        if triggered:
            orchestrator.handle_trigger_batch(triggered)
            logger.info(f"啟動時規則掃描完成：{len(triggered)} 條規則觸發")
        else:
            logger.info("啟動時規則掃描完成：無規則觸發")

        # 同步 _last_traffic_level，讓背景迴圈第一輪不會誤判為「新轉換」
        _last_traffic_level = sensing.traffic_level if sensing.traffic_level != "normal" else None
    except Exception as e:
        logger.warning(f"啟動時規則掃描失敗（不影響核心功能）: {e}")


_RULE_MONITOR_INTERVAL_SECONDS = 10
"""背景監測輪詢間隔，落在架構圖規定的 5~15 秒區間內（見
`.kiro/specs/architecture-reference/模組架構圖_整合版.md` 情境A：
「後端每 5~15 秒推進一次並以 WebSocket 主動推播」）。"""

_last_traffic_level: str | None = None
"""上一輪背景監測算出的全市交通等級（"A"/"B"/None），供跟這一輪比較找出轉換。
只有 `_periodic_rule_monitor` 這個背景迴圈會讀寫，不對外暴露。"""

_TZ_TAIPEI = timezone(timedelta(hours=8))

# 模擬時間狀態
_simulation_state = {
    "enabled": False,
    "current_time": None,  # datetime
    "start_time": None,    # 資料最早時間
    "end_time": None,      # 資料最晚時間
    "speed": 1,            # 1 = 即時, 60 = 1秒跑1分鐘
    "playing": False,
    "last_level": None,    # 上一次的等級，用於偵測變化
}

_decision_in_flight = 0
"""正在跑的決策週期數。大於 0 時模擬時鐘暫停前進。

[2026-08-02] 沒有這道閘門的話，模擬時間會在決策生成期間跑掉一大段：

    22:10 注入事件 → handle_incident() 開始
          plan_routes 用 as_of=22:10 → 主線市民大道四段(0.78)
          C1 建議書生成 ~20 秒（LLM）
    ← 這 20 秒內 tick loop 照跑，speed=60 → **模擬時間前進 20 分鐘**
    22:30 decision_result 才寫進 active_incidents

結果是 22:15（市民大道四段剛飽和、仁愛路四段還空著）那一刻沒有任何決策可以
重規劃——第一次路線更新就這樣消失了，而系統下一次看到路況已經是兩條都飽和。
使用者看到的「只更新一次、而且新舊路線相同」正是這樣來的。

決策本身是幾百毫秒的確定性運算 + 十幾秒的 LLM 敘述；讓模擬時鐘等它，
換來的是「事件在哪一分鐘發生，就用那一分鐘的路況決策」這個因果一致性。
真實時間（非模擬）不受影響——這個計數器只有 tick loop 會讀。
"""


@contextlib.contextmanager
def _hold_simulation_clock():
    """決策週期進行中暫停模擬時鐘；離開時恢復（例外也會恢復）。"""
    global _decision_in_flight
    _decision_in_flight += 1
    try:
        yield
    finally:
        _decision_in_flight -= 1


@app.on_event("startup")
async def _start_periodic_rule_monitor():
    """啟動背景週期性監測任務。"""
    import asyncio
    asyncio.create_task(_periodic_rule_monitor())
    asyncio.create_task(_simulation_tick_loop())  # 獨立的模擬器 tick 迴圈


async def _simulation_tick_loop() -> None:
    """模擬器專用迴圈：每 1 秒檢查是否要推進模擬時間。
    
    速度設定：speed=60 表示 1 秒推進 1 分鐘，speed=300 表示 1 秒推進 5 分鐘。
    """
    import asyncio
    
    while True:
        await asyncio.sleep(1)  # 每 1 秒 tick
        
        if not _simulation_state["enabled"] or not _simulation_state["playing"]:
            continue

        # 決策週期進行中就不推進時鐘——理由見 `_decision_in_flight` 的說明。
        # 只是「暫停」不是「丟棄」：決策一結束，下一秒就從原本的時間繼續跑。
        if _decision_in_flight > 0:
            continue

        if not _simulation_state["current_time"]:
            continue
        
        try:
            # 推進模擬時間：1 秒推進 speed 秒（換算成分鐘）
            speed = _simulation_state.get("speed", 60)
            advance_minutes = speed / 60  # speed=60 → 1分鐘, speed=300 → 5分鐘
            _simulation_state["current_time"] += timedelta(minutes=advance_minutes)
            
            # 檢查是否超過結束時間
            if _simulation_state["end_time"] and _simulation_state["current_time"] > _simulation_state["end_time"]:
                _simulation_state["current_time"] = _simulation_state["end_time"]
                _simulation_state["playing"] = False
                await ws_manager.broadcast({
                    "message_type": "simulation.state.v1",
                    "payload": {"action": "ended", "current_time": _simulation_state["current_time"].isoformat()}
                })
                continue
            
            # 推播時間更新
            await ws_manager.broadcast({
                "message_type": "simulation.tick.v1",
                "payload": {"current_time": _simulation_state["current_time"].isoformat()}
            })
            
            # 每分鐘做一次規則評估（避免太頻繁）
            current_minute = _simulation_state["current_time"].minute
            last_eval_minute = _simulation_state.get("last_eval_minute", -1)
            
            if current_minute != last_eval_minute:
                _simulation_state["last_eval_minute"] = current_minute
                await _evaluate_and_alert_at_simtime()
                
        except Exception as e:
            logger.warning(f"模擬器 tick 失敗: {e}")


async def _evaluate_and_alert_at_simtime() -> None:
    """在模擬時間做規則評估，針對每個路段獨立追蹤等級變化並彈窗。
    
    當偵測到路段飽和時，同時檢查該路段是否為某個活躍事件的推薦路線，
    若是則觸發路線重規劃並推播 routes.updated.v1。
    """
    import asyncio

    sim_time = _simulation_state.get("current_time")
    if not sim_time:
        return

    # 每個模擬分鐘都會跑一次，內含檔案 I/O 與全路段掃描（~100ms+）。
    # 留在 event loop 上會讓時鐘每分鐘頓一下，跟這次修掉的建議書阻塞是同一種病。
    bundle = await asyncio.to_thread(orchestrator.GATEWAY.load_data)
    
    # 初始化路段等級追蹤（如果還沒有）
    if "segment_levels" not in _simulation_state:
        _simulation_state["segment_levels"] = {}
    
    # 取得該時間點所有路段的飽和度
    from src.rules import get_saturation
    
    # 等級變化只用來決定「要不要跳飽和預警彈窗」（降級不發、同級不重發）。
    # 路線有效性監測**不再**依賴它——見下方 _monitor_active_routes 的呼叫說明。
    alerts_to_send = []

    for segment in bundle.road_network:
        seg_id = segment.segment_id
        sat = get_saturation(bundle, seg_id, sim_time)
        
        if sat is None:
            continue
        
        # 判定這條路段的等級
        if sat >= 0.95:
            current_level = "A"
        elif sat >= 0.85:
            current_level = "B"
        else:
            current_level = "normal"
        
        # 跟上次的等級比較
        last_level = _simulation_state["segment_levels"].get(seg_id, "normal")
        
        if current_level != last_level:
            _simulation_state["segment_levels"][seg_id] = current_level
            
            # 只有升級到 A 或 B 才發預警（降級不發）
            if current_level in ("A", "B"):
                road_name = segment.name or seg_id
                logger.info(f"[模擬 {sim_time.strftime('%H:%M')}] {road_name} 等級變化: {last_level} → {current_level}")
                
                alerts_to_send.append({
                    "level": current_level,
                    "segment_id": seg_id,
                    "road_name": road_name,
                    "saturation": round(sat, 2),
                    "time": sim_time.strftime('%H:%M'),
                })

    # 發送所有路段的預警
    for alert in alerts_to_send:
        await ws_manager.broadcast({
            "message_type": "decision.alert.v1",
            "payload": {
                "level": alert["level"],
                "description": f"[{alert['time']}] {alert['road_name']} 飽和度達 {alert['saturation']}",
                "segment_id": alert["segment_id"],
                "road_name": alert["road_name"],
                "saturation": alert["saturation"],
                "ete_minutes": None,
            },
        })
    
    # ★ 路線有效性監測。
    #
    # [2026-08-02 修正] 這裡原本是 `if saturated_segments: await _check...(saturated_segments)`
    # ——只有在**這一分鐘剛好發生等級變化**時才檢查路線。那是邊緣觸發，漏掉兩種情況：
    #
    #   1. 建議書還在生成時的飽和事件會被永久丟棄。實測時序：22:10 注入事件，
    #      C1 建議書要 ~20 秒（LLM），期間模擬時鐘照跑（speed=60 → 20 模擬分鐘）。
    #      22:15 市民大道四段 0.85 觸發等級變化，但此刻 `decision_result` 仍是 None，
    #      `_check_and_replan_affected_routes` 直接 `continue`——而等級已經被記成 B，
    #      這個路段之後再也不會「變化」，那次重規劃就此消失。
    #
    #   2. 路況繼續惡化但沒跨過等級門檻同樣不會觸發。22:45 市民大道四段
    #      0.95→0.98、仁愛路四段 0.85→0.92，兩條都更塞了，等級卻都沒變
    #      （A 仍是 A、B 仍是 B）→ 整段時間一次都沒再檢查過。
    #
    # 兩者合起來的結果是：整場模擬只在 22:30 觸發過一次重規劃，而那一次因為
    # 路線還停在 22:10 的規劃結果，主次線同時飽和，重規劃又選回同一條路，
    # 畫面就成了「✗ 原路線: 市民大道四段 ／ ✓ 新路線: 市民大道四段」。
    #
    # 改成每個模擬分鐘都檢查（狀態觸發）。重複推播由 orchestrator 的
    # `last_route_state_signature` 擋掉——比對在算完路線之後、生成建議書之前，
    # 所以狀況沒變時不會付出 LLM 的成本。
    await _monitor_active_routes(sim_time, bundle)

    # 推播 dashboard.updated.v1
    if alerts_to_send:
        await ws_manager.broadcast({
            "message_type": "dashboard.updated.v1",
            "payload": {"alerts": alerts_to_send},
        })


def _affected_route_type(routes, invalid_reasons: dict) -> str | None:
    """把失效路段對應回「主線／次線／兩者皆是」。

    以前這個分類是拿「本分鐘剛變飽和的路段」去比對，所以只認得得出**變化的那一刻**。
    改用 `check_route_validity()` 實際算出來的 `invalid_reasons`，任何時候檢查
    都能得到正確答案。
    """
    if routes is None:
        return None
    bad = set(invalid_reasons or {})
    primary_bad = bool(routes.primary and routes.primary.segment_id in bad)
    secondary_bad = bool(routes.secondary and routes.secondary.segment_id in bad)
    if primary_bad and secondary_bad:
        return "both"
    if primary_bad:
        return "primary"
    if secondary_bad:
        return "secondary"
    return None


async def _broadcast_replan_progress(event_id: str, as_of: datetime, phase: str) -> None:
    """路線重規劃的進度事件，沿用前端既有的 `decision.task_update.v1` 進度條。

    `eta_seconds` 是實測的建議書生成時間（見 orchestrator 的 `_TASK_ETA_SECONDS`）。
    這段期間模擬時鐘不會前進，有這條進度使用者才知道系統在忙而不是當掉。
    """
    record = orchestrator.get_global_state().active_incidents.get(event_id)
    payload = {
        "trace_id": record.trace_id if record else event_id,
        "dispatch_seq": (record.route_replan_count + 1) if record else 1,
        "status": "report_started" if phase == "started" else "report_done",
        "label": "路線重規劃・更新交控建議書" if phase == "started" else "交控建議書已更新",
        "event_id": event_id,
        "sim_time": as_of.isoformat(),
    }
    if phase == "started":
        payload["eta_seconds"] = 20
    try:
        await ws_manager.broadcast({
            "message_type": "decision.task_update.v1",
            "payload": payload,
        })
    except Exception:  # noqa: BLE001 - 推播失敗不該影響重規劃本身
        pass


async def _monitor_active_routes(as_of: datetime, bundle) -> None:
    """逐一檢查所有活躍事件的推薦路線是否仍然有效，失效則重規劃並推播。

    [2026-08-02] 由「等級變化才觸發」改為每個模擬分鐘都檢查（理由見呼叫端的說明）。
    真正的「要不要重規劃」判斷在 `routing.check_route_validity()`，這裡只負責
    掃描與推播；重複狀態由 orchestrator 的 `last_route_state_signature` 擋掉。
    """
    import asyncio

    state = orchestrator.get_global_state()

    for event_id, record in list(state.active_incidents.items()):
        if record.decision_result is None or record.decision_result.routes is None:
            # 建議書還在生成（LLM ~20 秒）或本來就不需要路網規劃。
            # 前者只是「這一分鐘還不能判斷」，下一分鐘會再檢查一次——**不再是永久丟棄**。
            if record.decision_result is None:
                logger.debug(f"[路線監測] {event_id} 決策尚未完成，本分鐘略過，稍後重試")
            continue

        old_routes = record.decision_result.routes

        # 先問再做：路線還有效就不必付出重規劃的代價（毫秒級查表）。
        #
        # [2026-08-02] 這一步不只是省時間，更是為了讓「時間當一下」有交代。
        # 重規劃成功時會重新生成建議書（LLM ~20 秒），而本函式是在模擬 tick
        # 迴圈裡被 await 的——那 20 秒模擬時鐘完全不動，使用者看到的就是畫面
        # 卡住。先預判、再推一則帶 eta 的進度事件，卡住的那段就有進度條可看，
        # 而不是無聲無息地停在某一分鐘。
        needs = await asyncio.to_thread(
            orchestrator.route_replan_needed, event_id, as_of, bundle
        )
        if not needs:
            continue

        await _broadcast_replan_progress(event_id, as_of, "started")
        try:
            result = await asyncio.to_thread(
                orchestrator.check_and_replan_routes, event_id, as_of
            )
        finally:
            await _broadcast_replan_progress(event_id, as_of, "done")

        if result and result.replanned:
            affected_route_type = _affected_route_type(old_routes, result.invalid_reasons)
            logger.info(
                f"[路線監測] 事件 {event_id} 路線失效（{affected_route_type}）："
                f"{result.invalid_reasons}"
            )
            # 推播 routes.updated.v1 通知前端
            # 包含新的報告內容，讓前端能夠同步更新報告卡片
            new_decision = result.new_decision_result
            new_routes = new_decision.routes if new_decision else None
            await ws_manager.broadcast({
                "message_type": "routes.updated.v1",
                "payload": {
                    "event_id": event_id,
                    # [2026-08-02] 「重規劃過」不等於「換了路」。候選全數飽和時
                    # 重規劃會再挑到同一條路，前端若只看 old/new 欄位就會畫出
                    # 「✗ 原路線: 市民大道四段 ／ ✓ 新路線: 市民大道四段」。
                    # 這三個旗標讓前端能區分「換路成功」與「已無路可替補」。
                    "reason": "NO_ALTERNATIVE_AVAILABLE" if result.no_alternative_available else "ROUTE_SATURATED",
                    "affected_route": affected_route_type,
                    "route_changed": result.route_changed,
                    "no_alternative_available": result.no_alternative_available,
                    "no_feasible_route": bool(new_routes and new_routes.no_feasible_route),
                    "all_alternatives_saturated": bool(new_routes and new_routes.all_alternatives_saturated),
                    "old_primary": result.old_primary,
                    "new_primary": result.new_primary,
                    "old_secondary": result.old_secondary,
                    "new_secondary": result.new_secondary,
                    "invalid_reasons": result.invalid_reasons,
                    "replan_count": record.route_replan_count,
                    "time": as_of.isoformat(),
                    # 新增：更新後的報告內容
                    "control_center_report": new_decision.control_center_report if new_decision else None,
                    "notifications": new_decision.notifications.model_dump(mode="json") if new_decision and new_decision.notifications else None,
                },
            })

            # 已無可替補路段時，額外推一則最高等級警報。routes.updated.v1 是
            # 「路線面板」的更新事件，這一則走的是警報通道——指揮官不會因為
            # 沒在看路線面板就漏掉「整個周邊路網都滿了」。
            if result.no_alternative_available:
                await ws_manager.broadcast({
                    "message_type": "decision.alert.v1",
                    "payload": {
                        "level": "A",
                        "severity": "Critical",
                        "event_id": event_id,
                        "description": (
                            f"⚠️ 嚴重警告：{event_id} 周邊已無可替補路段"
                            f"（候選路段全數飽和），請立即啟動人工指揮或區域封閉"
                        ),
                        "ete_minutes": new_decision.ete.minutes if new_decision and new_decision.ete else None,
                        "alert_type": "NO_FEASIBLE_ROUTE",
                    },
                })

            # 同時推播更新後的完整 decision result
            if result.new_decision_result:
                await ws_manager.broadcast({
                    "message_type": "decision.completed.v1",
                    "payload": result.new_decision_result.model_dump(mode="json"),
                })


async def _periodic_rule_monitor() -> None:
    """背景無限迴圈：每 _RULE_MONITOR_INTERVAL_SECONDS 秒重跑全量規則評估。
    
    注意：
    - 模擬器時間推進改由 _simulation_tick_loop 處理
    - 非模擬模式下，因為資料是靜態歷史資料，不做等級變化預警推播
      （避免每次輪詢都因為查到同樣的歷史資料而重複彈窗）
    """
    import asyncio

    while True:
        await asyncio.sleep(_RULE_MONITOR_INTERVAL_SECONDS)
        
        # 模擬器運行中，跳過（由 _simulation_tick_loop 處理）
        if _simulation_state["enabled"]:
            continue
        
        # 非模擬模式：只做一次性的規則評估供 Dashboard 顯示，不做預警推播
        # 因為資料是靜態歷史資料，持續推播沒有意義
        try:
            bundle = await asyncio.to_thread(orchestrator.GATEWAY.load_data)
            sensing = await asyncio.to_thread(
                orchestrator.GATEWAY.evaluate_rules, bundle, None
            )

            # 只推播 rules.evaluated.v1 讓 F1 顯示，不做 alert
            sensing_payload = sensing.model_dump(mode="json")
            await ws_manager.broadcast({
                "message_type": "rules.evaluated.v1",
                "payload": sensing_payload,
            })

        except Exception as e:
            logger.warning(f"背景規則監測失敗: {e}")


# [2026-08-02 移除 `_evaluate_rules_at_time()`]
# ------------------------------------------
# 這是 `src/rules.py::evaluate_rules()` 的第二份實作：同樣掃 SOP-1/3/6、同樣的
# 門檻數字、連 `_CITY_RESPONSE_SEGMENTS` 都各自寫了一份。它在 `evaluate_rules()`
# 還沒有 `as_of` 參數的年代是必要的權宜之計，那個參數 [2026-08-01] 補上之後
# 它就再也沒有被呼叫過（全 repo 只剩定義本身）。
#
# 留著的風險是實質的：兩份規則引擎會漂移，而這一份少了 SOP-2/4/5/7、
# 少了 SOP-4→SOP-3 連動，等級判定也是自己重算一遍。哪天有人「順手」接回去，
# 建議書與 Dashboard 就會開始各說各話。
#
# 要在指定時刻評估規則請用 `evaluate_rules(bundle, incident, as_of)`。


class SafeStaticFiles(StaticFiles):
    """StaticFiles，但畸形路徑回 404 而不是 500。

    [2026-08-01 實測] Windows 上只要網址含檔名非法字元（`*` `?` `:` `<` `>` `|`），
    `os.stat()` 會拋 `OSError: [WinError 123] 檔案名稱、目錄名稱或磁碟區標籤語法錯誤`，
    而 Starlette 的 `StaticFiles.lookup_path()` 只接 `FileNotFoundError`，於是這個
    OSError 一路往上炸成 **HTTP 500 + 整頁 traceback**。

    實際觸發的請求（真的發生過）：
        GET /frontend/%2A%2A%EF%BC%88%E8%A8%98%E5%BE%97...
        → 解碼後是 `/frontend/**（記得重新整理，或用`

    來源是聊天訊息裡的網址被 Markdown 粗體符號吃進去，點下去就送出畸形路徑。
    使用者手殘打錯網址也會一樣。**找不到的東西就該回 404**，不該讓 Demo 現場
    的主控台噴一頁紅字，看起來像系統壞了。

    只攔 OSError（含 ValueError——路徑含 NUL 位元組時是這個），其餘例外照常往上，
    不會掩蓋真正的伺服器錯誤。
    """

    def lookup_path(self, path: str):
        try:
            return super().lookup_path(path)
        except (OSError, ValueError):
            # 回 ("", None) 是 Starlette 對「找不到」的既定表示法，
            # 上層 get_response() 看到 None 就會回 404。
            logger.debug("靜態檔路徑不合法，回 404: %r", path)
            return "", None


# frontend/ 掛在 /frontend（不是 /），API 前綴 /api 與 /ws 不會被靜態路由吃掉。
app.mount("/frontend", SafeStaticFiles(directory="frontend", html=True), name="frontend")
# data/ 掛載供前端 fetch display_geometry.json（僅 SVG 顯示用，不參與演算）
app.mount("/data", SafeStaticFiles(directory="data"), name="data")


@app.exception_handler(Exception)
async def unified_exception_handler(request: Request, exc: Exception):
    """三個 Envelope 端點共用例外處理器，把例外收斂成 status="error"。
    GET /api/health 不套用此處理器（不使用 Envelope）。
    """
    import asyncio

    # /api/health 不走 Envelope 格式
    if request.url.path == "/api/health":
        return JSONResponse(
            status_code=500,
            content={"status": "error", "message": str(exc)},
        )

    # 錯誤碼映射
    if isinstance(exc, ValidationError):
        code = "VALIDATION_ERROR"
        field = None
        try:
            field = exc.errors()[0].get("loc", [None])[-1]
        except (IndexError, AttributeError):
            pass
        errors = [{"code": code, "message": str(exc), "field": field}]
    elif isinstance(exc, ValueError):
        # DATA_NOT_FOUND 情境（event_id 不存在等）
        msg = str(exc)
        if "不存在" in msg or "not found" in msg.lower() or "DATA_NOT_FOUND" in msg:
            code = "DATA_NOT_FOUND"
        else:
            code = "VALIDATION_ERROR"
        errors = [{"code": code, "message": msg}]
    elif isinstance(exc, asyncio.TimeoutError):
        errors = [{"code": "TIMEOUT", "message": "操作逾時"}]
    elif isinstance(exc, NotImplementedError):
        errors = [{"code": "INTERNAL_ERROR", "message": f"功能尚未實作: {exc}"}]
    else:
        errors = [{"code": "INTERNAL_ERROR", "message": str(exc)}]

    return JSONResponse(
        status_code=200,
        content={"status": "error", "errors": errors},
    )


@app.get("/api/dashboard")
async def get_dashboard():
    """回傳 message_type=dashboard.updated.v1 的 DashboardPayload。"""
    from datetime import datetime, timezone, timedelta
    from src.models import DashboardPayload, KpiSummary, DataProvenance

    state = orchestrator.get_global_state()
    bundle = orchestrator.GATEWAY.load_data()

    # KPI 計算
    active_incidents = list(state.active_incidents.values())
    active_count = len(active_incidents)

    # 目前最高應變等級
    current_level = None
    if active_incidents:
        for record in active_incidents:
            if record.decision_result and record.decision_result.level:
                if record.decision_result.level == "A":
                    current_level = "A"
                    break
                elif record.decision_result.level == "B" and current_level != "A":
                    current_level = "B"

    # 全路網平均飽和度
    saturations = [t.saturation_score for t in bundle.traffic if t.saturation_score is not None]
    avg_sat = sum(saturations) / len(saturations) if saturations else None

    # SOP-6 觸發站點數
    #
    # [2026-08-02] 這裡原本用 `datetime.now()`（真實時間）去查漫遊比率，
    # 而 `get_roaming_ratio()` 是 as-of 查詢——它會找**最接近該時刻**的那筆
    # 人流資料。Demo 在下午跑、資料集是晚上 17:00~23:30 的，於是這個數字
    # 一直是拿資料集邊界的那筆算出來的，跟畫面上的時刻無關。
    # 改讀 `clock.now()`：模擬器跑到幾點，就算幾點的漫遊比率。
    from src.clock import now as _clock_now
    from src.rules import get_roaming_ratio
    as_of = _clock_now()
    all_stations = {c.station_id for c in bundle.crowd}
    multilingual_count = sum(
        1 for sid in all_stations
        if (r := get_roaming_ratio(bundle, sid, as_of)) is not None and r >= 0.30
    )

    # 系統模式
    # [2026-08-01] 原本是 `"live" if os.getenv("USE_BEDROCK") else "degraded"`——
    # 讀旗標，所以憑證失效時 KPI 卡片照樣顯示「Live」。改讀實際探測結果。
    # `unknown`（還沒驗證完）由前端顯示成「檢查中」，不冒充 Live。
    from src import bedrock_status
    system_mode = bedrock_status.get_status()["mode"]

    kpis = KpiSummary(
        crowd_data_classification=DataProvenance.PROVIDED,
        active_incident_count=active_count,
        current_level=current_level,
        average_saturation=round(avg_sat, 4) if avg_sat is not None else None,
        multilingual_alert_count=multilingual_count,
        system_mode=system_mode,
    )

    # 活躍事件清單
    active_incident_models = [r.incident for r in active_incidents]

    payload = DashboardPayload(
        kpis=kpis,
        active_incidents=active_incident_models,
        as_of=as_of,
    )

    return JSONResponse(content={
        "status": "ok",
        "message_type": "dashboard.updated.v1",
        "payload": payload.model_dump(mode="json"),
        "traffic_samples": [
            {"timestamp": t.timestamp.isoformat(), "saturation_score": t.saturation_score, "segment_id": t.segment_id}
            for t in bundle.traffic
            if t.saturation_score is not None
        ],
    })


@app.post("/api/incidents/evaluate")
async def evaluate_incident(body: dict):
    """body={"event_id": str, "as_of": str (optional)}；呼叫 handle_incident()，回傳 decision.completed.v1。
    
    as_of: 可選，ISO 時間字串。若提供（模擬器模式），用此時間做飽和度查詢；
           若未提供，用事件本身的 timestamp。
    """
    event_id = body.get("event_id")
    as_of_str = body.get("as_of")  # ★ 模擬器當前時間
    
    if not event_id:
        return JSONResponse(status_code=200, content={
            "status": "error",
            "errors": [{"code": "VALIDATION_ERROR", "message": "event_id 為必填"}],
        })

    # 從 bundle 找對應事件
    bundle = orchestrator.GATEWAY.load_data()
    matched = [i for i in bundle.incidents if i.event_id == event_id]
    if not matched:
        return JSONResponse(status_code=200, content={
            "status": "error",
            "errors": [{"code": "DATA_NOT_FOUND", "message": f"event_id '{event_id}' 不存在"}],
        })

    incident = matched[0]
    
    # 決定事件的評估時刻，並覆寫 incident.timestamp
    # （handle_incident 內部的 as-of 查詢、ETE、recovery_at、風險推演全都以它為準）。
    #
    # [2026-08-02 改為後端決定]
    # ------------------------
    # 原本只有「前端有送 as_of 才覆寫」。前端送不送取決於 `SimState.enabled`，
    # 只要那個旗標沒對上（模擬器由另一個分頁啟動、頁面剛重新整理還沒同步狀態、
    # 或使用者用 API 直接注入），就會落到事件自己的 timestamp 或真實牆上時間，
    # 於是建議書寫「封閉時刻 14:11、90 分鐘後（15:41）恢復」——那是這台機器的
    # 現在幾點，跟畫面上的模擬時刻、跟資料集（2026-05-20 17:00~23:15）全都無關。
    #
    # 模擬器在跑的時候，「現在」的唯一權威是後端的 `_simulation_state`，
    # 不是前端送來的欄位。前端的 as_of 降級為模擬器沒在跑時的備援。
    as_of_time: datetime | None = clock.simulation_time()
    as_of_source = "simulation"
    if as_of_time is None and as_of_str:
        try:
            as_of_time = datetime.fromisoformat(as_of_str)
            if as_of_time.tzinfo is None:
                as_of_time = as_of_time.replace(tzinfo=_TZ_TAIPEI)
            as_of_source = "request"
        except Exception as e:
            logger.warning(f"解析 as_of 時間失敗: {as_of_str}, {e}")
            as_of_time = None

    if as_of_time is not None:
        incident = incident.model_copy(update={"timestamp": as_of_time})
        logger.info(
            f"[評估時刻] 事件 {event_id} 使用 {as_of_time.strftime('%Y-%m-%d %H:%M')}"
            f"（來源：{as_of_source}）"
        )

    # 廣播 decision.cycle_start.v1（週期開始，不帶 trace_id — 真正的 trace_id
    # 由 handle_incident 內部產生，避免格式對不上）
    await ws_manager.broadcast({
        "message_type": "decision.cycle_start.v1",
        "payload": {"triggered_by": [event_id]},
    })

    # 決策期間（含 ~20 秒的建議書生成）暫停模擬時鐘，確保路網規劃用的是
    # 事件實際發生的那一分鐘的路況，而不是生成結束後已經跑掉 20 分鐘的路況。
    with _hold_simulation_clock():
        decision_result = await orchestrator.handle_incident(incident, ws_broadcaster=ws_manager.broadcast)
    payload_json = decision_result.model_dump(mode="json")

    # 廣播 decision.alert.v1（所有事件注入都發送警報）
    # severity 用於顯示事件嚴重度，level 用於顯示交通應變等級
    await ws_manager.broadcast({
        "message_type": "decision.alert.v1",
        "payload": {
            "level": decision_result.level,  # A/B/null（交通等級）
            "severity": incident.severity,    # Critical/High/Medium（事件嚴重度）
            "description": incident.description,
            "type": incident.type,
            "location": incident.location,
            "event_id": incident.event_id,
            "ete_minutes": decision_result.ete.minutes if decision_result.ete else None,
        },
    })

    # ★ 情境3：檢查是否為「無可用替代路線」的嚴重情況
    # [2026-08-02] 加上 all_alternatives_saturated：候選全數飽和時 routing 會依
    # SOP-2 §2a 例外指派最不糟的那條，`no_feasible_route` 因此是 False——但指揮官
    # 面對的實際狀況一樣是「沒有路可以替補」，這則警報不能因為系統勉強給得出一個
    # 路段名稱就不發。
    if decision_result.routes and (
        decision_result.routes.no_feasible_route
        or decision_result.routes.all_alternatives_saturated
    ):
        _saturated_only = not decision_result.routes.no_feasible_route
        await ws_manager.broadcast({
            "message_type": "decision.alert.v1",
            "payload": {
                "level": "A",  # 無可用路線視為最高等級
                "severity": "Critical",
                "description": (
                    f"⚠️ 嚴重警告：{incident.location} 周邊候選路段全數飽和，已無可替補路段！"
                    if _saturated_only
                    else f"⚠️ 嚴重警告：{incident.location} 附近已無可用替代路線！"
                ),
                "ete_minutes": None,
                "alert_type": "NO_FEASIBLE_ROUTE",
            },
        })

    # ★ 情境2：檢查是否影響其他活躍事件的替代路線（連鎖衝突）
    await _check_cascade_impact(incident)

    # 廣播 decision.completed.v1
    await ws_manager.broadcast({
        "message_type": "decision.completed.v1",
        "payload": payload_json,
    })

    # 廣播 dashboard.updated.v1（決策完成後現況變動）
    await ws_manager.broadcast({
        "message_type": "dashboard.updated.v1",
        "payload": {"event_id": event_id, "level": decision_result.level},
    })

    return JSONResponse(content={
        "status": "ok",
        "message_type": "decision.completed.v1",
        "payload": payload_json,
    })


@app.post("/api/what-if")
async def what_if(body: dict):
    """對話端點：回溯追問 → M4B，其餘 → W1 Agent（路由見 `handle_user_query`）。"""
    import asyncio
    from dataclasses import asdict

    session_id = body.get("session_id", "")
    content = body.get("content", "")
    current_trace_id = body.get("current_trace_id")
    correlation_id = body.get("correlation_id", session_id)

    if not session_id or not content:
        return JSONResponse(status_code=200, content={
            "status": "error",
            "errors": [{"code": "VALIDATION_ERROR", "message": "session_id 與 content 為必填"}],
        })

    # [2026-08-01 修正：這一行原本會凍結整個伺服器]
    # `handle_user_query()` 是同步函式，裡面是最長 60 秒的阻塞 Bedrock 呼叫
    # （`llm.AGENT_TIMEOUT_S`）。直接在 `async def` 端點裡呼叫等於霸佔 event loop：
    # 那 60 秒內 WebSocket 推播、模擬器 tick（`_simulation_tick_loop`）、其他 API
    # 全部停擺。決策週期那邊早就用 `asyncio.to_thread` 處理過同樣的問題
    # （`orchestrator.py` 的 A2 規劃器），只有這裡漏了。
    #
    # 附帶修好 loading 進度條：`agent/loading.py` 用 `asyncio.ensure_future()`
    # 排推播，但 loop 被佔住時那些 coroutine 一個都跑不了，要等端點回傳才會被
    # 執行——使用者看到的是「空白 30 秒，然後 loading 跟答案同時出現」。
    # 現在主流程讓出 loop，推播就會即時送達。
    #
    # ContextVar（`orchestrator._current_trace_ctx`）由 `asyncio.to_thread` 自動
    # 複製到工作執行緒，不需要額外處理。
    result = await asyncio.to_thread(
        orchestrator.handle_user_query,
        question=content,
        current_trace_id=current_trace_id,
        session_id=session_id,
        correlation_id=correlation_id,
        ws_broadcaster=ws_manager.broadcast,
    )

    message_type = result["message_type"]
    payload = result["payload"]

    # W1Response 是 dataclass，需要轉成 dict
    if hasattr(payload, "__dataclass_fields__"):
        payload = asdict(payload)

    return JSONResponse(content={
        "status": "ok",
        "message_type": message_type,
        "payload": payload,
    })


@app.get("/api/notify/line/status")
async def line_status():
    """LINE 通報設定好了沒。前端據此決定按鈕要不要 disable、顯示什麼提示。

    刻意**不回傳 token 本身**，只回傳「有沒有設定」與收件模式。
    """
    from src import line_notify

    ok, reason = line_notify.is_configured()
    return {
        "status": "ok",
        "configured": ok,
        "reason": reason,
        "mode": "push" if os.getenv("LINE_TO_USER_ID", "").strip() else "broadcast",
    }


@app.post("/api/notify/line")
async def send_line_notification(body: dict):
    """把某起事件的通報送到 LINE。

    body = {"event_id": str, "lang": "zh"|"en"|"ja"|"ko", "force": bool}

    送出的是 **C4 多語通報**（本來就是為了發給民眾的簡訊而生成的），
    不是交控建議書全文——後者好幾百字，在手機上是一整片牆。

    對外發送是不可逆的動作，所以只有使用者按下按鈕才會走到這裡；
    決策週期本身不會自動發送（見 README「LINE 通報設定」的說明）。
    """
    import asyncio

    from src import line_notify

    event_id = (body or {}).get("event_id", "")
    lang = (body or {}).get("lang", "zh")
    force = bool((body or {}).get("force", False))

    if not event_id:
        return JSONResponse(status_code=200, content={
            "status": "error",
            "errors": [{"code": "VALIDATION_ERROR", "message": "event_id 為必填"}],
        })

    state = orchestrator.get_global_state()
    record = state.active_incidents.get(event_id) or state.resolved_incidents.get(event_id)
    if record is None or record.decision_result is None:
        return JSONResponse(status_code=200, content={
            "status": "error",
            "errors": [{"code": "DATA_NOT_FOUND", "message": f"找不到事件 {event_id} 的決策結果"}],
        })

    decision = record.decision_result
    text = line_notify.build_incident_message(
        incident=record.incident,
        notification=decision.notifications,
        ete=decision.ete,
        routes=decision.routes,
        lang=lang,
    )

    # 外部 HTTP 呼叫丟到工作執行緒，別佔住 event loop——模擬時鐘與 WebSocket
    # 推播跟它共用同一個 loop（這個教訓在 handle_incident 上學過一次了）。
    result = await asyncio.to_thread(line_notify.send_text, text, force=force)

    return JSONResponse(content={
        "status": "ok" if result.ok else "error",
        "payload": {
            "ok": result.ok,
            "mode": result.mode,
            "detail": result.detail,
            "sent_text": result.sent_text,
            "sent_at": result.sent_at,
            "diagnostics": result.diagnostics,
        },
    })


@app.post("/api/chat/assumptions/drop")
async def drop_chat_assumption(body: dict):
    """移除單一假設條件（對話框的假設 chip 按 ×）。

    [2026-08-02] 比「整段對話重來」精細：使用者常常只是想拿掉其中一個假設繼續問，
    不需要連前面問過的東西一起丟。回傳剩下的假設讓前端重畫 chips。
    """
    session_id = body.get("session_id", "")
    key = body.get("key", "")
    if not session_id or not key:
        return JSONResponse(status_code=200, content={
            "status": "error",
            "errors": [{"code": "VALIDATION_ERROR", "message": "session_id 與 key 為必填"}],
        })

    from src.session.session_manager import drop_assumption

    remaining = drop_assumption(session_id, key)
    return JSONResponse(content={"status": "ok", "active_assumptions": remaining})


@app.get("/api/health")
async def health(probe: bool = False):
    """不使用 Envelope。回傳系統實際狀態（不是設定檔寫了什麼）。

    [2026-08-01 修正：這個端點原本會騙人]
    ------------------------------------
    原本回傳的 `use_bedrock` 是直接讀 `os.getenv("USE_BEDROCK")`——那是「允不允許
    呼叫」的旗標，不是「呼叫通不通」。憑證失效時這裡照樣回 `true`，而建議書
    早就退成模板版了。Demo 前想確認「我現在真的在用 Bedrock 模型嗎」，這個端點
    給不出答案。

    現在多回一個 `bedrock` 區塊，內容來自 `src/bedrock_status`——啟動探測與每次
    真實 LLM 呼叫的結果都會寫進去。`active_model_id` 是**最後一次成功呼叫實際
    送出的模型 ID**，這是「我到底在用哪個模型」唯一可信的答案。

    Args:
        probe: `?probe=true` 時當場重新探測一次（Demo 前確認用）。預設讀快取，
            避免每次健康檢查都花一次 Bedrock 呼叫。
    """
    import asyncio

    from src import bedrock_status
    from src.orchestrator import StubGateway, LiveGateway

    if probe:
        await asyncio.to_thread(bedrock_status.probe)

    status = bedrock_status.get_status()

    gw = orchestrator.GATEWAY
    if isinstance(gw, StubGateway):
        gateway_mode = "stub"
    elif isinstance(gw, LiveGateway):
        gateway_mode = "live"
    else:
        gateway_mode = "mixed"

    return {
        "status": "ok",
        # 保留舊欄位：既有的前端輪詢與 preflight 都讀它，不要為了改結構破壞它們。
        # 但語意已經釐清——它是旗標，實況看 `bedrock` 區塊。
        "use_bedrock": status["enabled"],
        "gateway_mode": gateway_mode,
        "bedrock": status,
    }


@app.get("/api/trace/{trace_id}")
async def get_trace(trace_id: str):
    """取得決策軌跡全文，供前端「決策軌跡」面板與對話卡片使用。

    [2026-08-01 新增] 在此之前決策軌跡**沒有任何對外出口**——`decision_trace`
    模組只被 M4B 生成層在行程內讀取。前端 F7「決策依據」分頁看起來像在顯示軌跡，
    其實是自己從 WebSocket 的 task_update 事件拼的活動紀錄（「發生了什麼」，
    不是「依據什麼判斷」），而且斷線就永久缺一塊。

    軌跡存在行程記憶體（`DECISION_LOG_TABLE` 那條 DynamoDB 路線從未實作），
    所以伺服器重啟後舊的 trace_id 會查不到——回 DATA_NOT_FOUND 而不是 500。
    """
    from src.decision_trace import get_trace_view

    view = get_trace_view(trace_id)
    if view is None:
        return JSONResponse(status_code=200, content={
            "status": "error",
            "errors": [{
                "code": "DATA_NOT_FOUND",
                "message": f"找不到決策軌跡 {trace_id}（軌跡存在記憶體，伺服器重啟後即消失）",
            }],
        })

    return JSONResponse(content={
        "status": "ok",
        "message_type": "trace.view.v1",
        "payload": view,
    })


@app.get("/api/incidents")
async def list_incidents(as_of: str = None):
    """取得可用事件列表（供前端事件注入面板動態顯示）。
    
    Args:
        as_of: 可選，ISO 時間字串或 HH:MM 格式。若提供，只回傳 timestamp <= as_of 的事件。
               用於模擬器模式，讓事件隨時間推進逐步出現。
    """
    bundle = orchestrator.GATEWAY.load_data()
    
    # 解析 as_of 時間
    cutoff_time = None
    if as_of:
        try:
            if len(as_of) == 5 and ":" in as_of:
                # HH:MM 格式，用資料中最早的日期補齊
                traffic_times = [t.timestamp for t in bundle.traffic if t.timestamp]
                if traffic_times:
                    base_date = min(traffic_times).date()
                    hour, minute = map(int, as_of.split(":"))
                    cutoff_time = datetime(base_date.year, base_date.month, base_date.day, hour, minute, tzinfo=_TZ_TAIPEI)
            else:
                cutoff_time = datetime.fromisoformat(as_of)
                if cutoff_time.tzinfo is None:
                    cutoff_time = cutoff_time.replace(tzinfo=_TZ_TAIPEI)
        except Exception as e:
            logger.warning(f"解析 as_of 時間失敗: {as_of}, {e}")
    
    incidents = []
    for inc in bundle.incidents:
        # 若有 cutoff_time，只回傳 timestamp <= cutoff_time 的事件
        if cutoff_time and inc.timestamp:
            if inc.timestamp > cutoff_time:
                continue  # 這個事件還沒發生
        
        incidents.append({
            "event_id": inc.event_id,
            "type": inc.type,
            "location": inc.location,
            "severity": inc.severity.value,
            "status": inc.status,
            "description": inc.description,
            "affected_segment": inc.affected_segment,
            "timestamp": inc.timestamp.isoformat() if inc.timestamp else None,
        })
    
    return {"status": "ok", "incidents": incidents, "as_of": as_of}


@app.post("/api/reset")
async def reset_state():
    """重設後端狀態（清空 active_incidents），供開發測試用。"""
    orchestrator.reset()
    return {"status": "ok", "message": "後端狀態已重設"}


# ========== 時間軸模擬器 API ==========

def _get_data_time_range():
    """取得資料的時間範圍"""
    bundle = orchestrator.GATEWAY.load_data()
    traffic_times = [t.timestamp for t in bundle.traffic]
    crowd_times = [c.timestamp for c in bundle.crowd]
    all_times = traffic_times + crowd_times
    if not all_times:
        return None, None
    return min(all_times), max(all_times)


def get_simulation_time():
    """取得當前模擬時間（供其他模組使用）"""
    if _simulation_state["enabled"] and _simulation_state["current_time"]:
        return _simulation_state["current_time"]
    return None


# ========== 多事件衝突處理 API ==========

async def _check_cascade_impact(new_incident) -> None:
    """情境2：檢查新事件是否影響其他活躍事件的替代路線，若是則觸發重規劃。
    
    當 B 事件封閉了 A 事件的替代路線時，A 需要重新規劃。
    """
    affected_seg = new_incident.affected_road or new_incident.affected_segment
    if not affected_seg:
        return
    
    state = orchestrator.get_global_state()
    as_of = new_incident.timestamp or clock.now()
    
    for event_id, record in list(state.active_incidents.items()):
        if event_id == new_incident.event_id:
            continue  # 跳過自己
        
        if record.decision_result is None or record.decision_result.routes is None:
            continue
        
        routes = record.decision_result.routes
        primary_blocked = routes.primary and routes.primary.segment_id == affected_seg
        secondary_blocked = routes.secondary and routes.secondary.segment_id == affected_seg
        
        if primary_blocked or secondary_blocked:
            logger.info(f"[連鎖衝突] {new_incident.event_id} 封閉了 {event_id} 的替代路線，觸發重規劃")
            
            # 觸發重規劃
            result = orchestrator.check_and_replan_routes(event_id, as_of)
            
            if result and result.replanned:
                # 推播路線變更警報
                await ws_manager.broadcast({
                    "message_type": "decision.alert.v1",
                    "payload": {
                        "level": result.new_decision_result.level if result.new_decision_result else "B",
                        "severity": "High",
                        "description": f"[路線更新] {event_id} 的替代路線已變更（原路線被 {new_incident.event_id} 封閉）",
                        "ete_minutes": result.new_decision_result.ete.minutes if result.new_decision_result and result.new_decision_result.ete else None,
                        "alert_type": "ROUTE_CHANGED",
                        "old_primary": result.old_primary,
                        "new_primary": result.new_primary,
                    },
                })
                
                # 推播更新後的決策結果
                if result.new_decision_result:
                    await ws_manager.broadcast({
                        "message_type": "decision.completed.v1",
                        "payload": result.new_decision_result.model_dump(mode="json"),
                    })


@app.post("/api/incidents/{event_id}/resolve")
async def resolve_incident_endpoint(event_id: str, body: dict = None):
    """情境4：手動解除事件，釋放路段，讓其他事件可以重新評估。
    
    使用 orchestrator.resolve_incident() 核心邏輯，包含：
    1. 從 active_incidents 移除並保存到 resolved_incidents
    2. 連鎖重規劃：檢查釋放的路段是否影響其他活躍事件的路線
    3. 推播所有相關更新
    """
    body = body or {}
    new_status = body.get("status", "Resolved")
    
    # 呼叫 orchestrator 的核心邏輯
    result = orchestrator.resolve_incident(event_id, new_status)
    
    if result is None:
        return JSONResponse(status_code=200, content={
            "status": "error",
            "errors": [{"code": "DATA_NOT_FOUND", "message": f"事件 {event_id} 不存在於活躍清單"}],
        })
    
    # 推播事件解除通知
    await ws_manager.broadcast({
        "message_type": "incident.resolved.v1",
        "payload": {
            "event_id": result.event_id,
            "freed_segment": result.freed_segment,
            "resolved_at": result.resolved_at.isoformat(),
            "new_status": new_status,
            "affected_incidents": result.affected_incidents,
        },
    })
    
    # 對每個重規劃的事件推播更新
    for replan_result in result.replan_results:
        if not replan_result.replanned:
            continue
        
        # 推播路線變更警報
        await ws_manager.broadcast({
            "message_type": "routes.updated.v1",
            "payload": {
                "event_id": replan_result.event_id,
                "reason": "SEGMENT_FREED",
                "freed_by": event_id,
                "freed_segment": result.freed_segment,
                "old_primary": replan_result.old_primary,
                "new_primary": replan_result.new_primary,
                "old_secondary": replan_result.old_secondary,
                "new_secondary": replan_result.new_secondary,
                "time": result.resolved_at.isoformat(),
            },
        })
        
        # 推播友善提示
        new_primary_name = replan_result.new_primary or "(無)"
        old_primary_name = replan_result.old_primary or "(無)"
        await ws_manager.broadcast({
            "message_type": "decision.alert.v1",
            "payload": {
                "level": "B",
                "severity": "Medium",
                "description": f"[路線優化] {replan_result.event_id} 發現更佳替代路線（{result.freed_segment} 已解封）：{old_primary_name} → {new_primary_name}",
                "alert_type": "ROUTE_OPTIMIZED",
                "old_primary": replan_result.old_primary,
                "new_primary": replan_result.new_primary,
            },
        })
        
        # 推播更新後的完整決策結果
        if replan_result.new_decision_result:
            await ws_manager.broadcast({
                "message_type": "decision.completed.v1",
                "payload": replan_result.new_decision_result.model_dump(mode="json"),
            })
    
    # 推播 dashboard.updated.v1（KPI 變動：active_incident_count 減少）
    await ws_manager.broadcast({
        "message_type": "dashboard.updated.v1",
        "payload": {
            "reason": "INCIDENT_RESOLVED",
            "event_id": event_id,
            "freed_segment": result.freed_segment,
            "affected_incidents": result.affected_incidents,
        },
    })
    
    return JSONResponse(content={
        "status": "ok",
        "message": f"事件 {event_id} 已解除",
        "freed_segment": result.freed_segment,
        "resolved_at": result.resolved_at.isoformat(),
        "affected_incidents": result.affected_incidents,
        "replan_count": len([r for r in result.replan_results if r.replanned]),
    })


@app.patch("/api/incidents/{event_id}")
async def update_incident(event_id: str, body: dict):
    """情境5：更新事件屬性（如 severity 升級），觸發重新評估。"""
    state = orchestrator.get_global_state()
    record = state.active_incidents.get(event_id)
    
    if record is None:
        return JSONResponse(status_code=200, content={
            "status": "error",
            "errors": [{"code": "DATA_NOT_FOUND", "message": f"事件 {event_id} 不存在於活躍清單"}],
        })
    
    old_severity = record.incident.severity.value
    new_severity = body.get("severity")
    new_status = body.get("status")
    
    changes = []
    
    if new_severity and new_severity != old_severity:
        from src.models import IncidentSeverity
        record.incident.severity = IncidentSeverity(new_severity)
        changes.append(f"severity: {old_severity} → {new_severity}")
        logger.info(f"[事件升級] {event_id} severity 從 {old_severity} 升級為 {new_severity}")
    
    if new_status and new_status != record.incident.status:
        old_status = record.incident.status
        record.incident.status = new_status
        changes.append(f"status: {old_status} → {new_status}")
    
    if not changes:
        return JSONResponse(content={"status": "ok", "message": "無變更"})
    
    # 重新評估。用模擬器時刻——事件狀態變更是在被模擬的世界裡發生的，
    # 拿真實時間重算會在另一個時段的路況上算路線。
    bundle = orchestrator.GATEWAY.load_data()
    as_of = clock.now()
    
    # 重新計算 ETE
    new_ete = orchestrator.GATEWAY.calculate_ete(record.incident, bundle)
    
    # 重新規劃路線（如果需要）
    classification = orchestrator.classify_incident(record.incident)
    new_routes = None
    if classification["requires_rerouting"]:
        from src.models import RouteRequest
        new_routes = orchestrator.GATEWAY.plan_routes(
            RouteRequest(incident=record.incident, bundle=bundle, as_of=as_of)
        )
    
    # 更新 decision_result
    if record.decision_result:
        record.decision_result.ete = new_ete
        if new_routes:
            record.decision_result.routes = new_routes
    
    # 推播警報
    await ws_manager.broadcast({
        "message_type": "decision.alert.v1",
        "payload": {
            "level": record.decision_result.level if record.decision_result else None,
            "severity": record.incident.severity.value,
            "description": f"[事件更新] {event_id} {', '.join(changes)}，ETE 重算為 {new_ete.minutes} 分鐘",
            "ete_minutes": new_ete.minutes,
            "alert_type": "INCIDENT_UPDATED",
        },
    })
    
    # 推播更新的決策結果
    if record.decision_result:
        await ws_manager.broadcast({
            "message_type": "decision.completed.v1",
            "payload": record.decision_result.model_dump(mode="json"),
        })
    
    return JSONResponse(content={
        "status": "ok",
        "message": f"事件 {event_id} 已更新",
        "changes": changes,
        "new_ete_minutes": new_ete.minutes,
    })


@app.get("/api/incidents/history")
async def get_incident_history():
    """取得所有事件歷史（含活躍中的）。"""
    state = orchestrator.get_global_state()
    incidents = []
    
    for event_id, record in state.active_incidents.items():
        incidents.append({
            "event_id": event_id,
            "incident": {
                "event_id": record.incident.event_id,
                "type": record.incident.type,
                "location": record.incident.location,
                "severity": record.incident.severity.value,
                "status": record.incident.status,
            },
            "trace_id": record.trace_id,
            "has_decision": record.decision_result is not None,
            "replan_count": record.route_replan_count,
        })
    
    return {"status": "ok", "incidents": incidents}


@app.get("/api/simulation")
async def get_simulation_state():
    """取得模擬器狀態"""
    start_time, end_time = _get_data_time_range()
    
    return {
        "status": "ok",
        "simulation": {
            "enabled": _simulation_state["enabled"],
            "playing": _simulation_state["playing"],
            "current_time": _simulation_state["current_time"].isoformat() if _simulation_state["current_time"] else None,
            "start_time": start_time.isoformat() if start_time else None,
            "end_time": end_time.isoformat() if end_time else None,
            "speed": _simulation_state["speed"],
        }
    }


@app.post("/api/simulation/start")
async def start_simulation(body: dict = None):
    """啟動模擬器"""
    body = body or {}
    start_time, end_time = _get_data_time_range()
    
    if not start_time or not end_time:
        return {"status": "error", "message": "無法取得資料時間範圍"}
    
    _simulation_state["enabled"] = True
    _simulation_state["start_time"] = start_time
    _simulation_state["end_time"] = end_time
    # 起播位置一律是資料起點，不做任何「聰明」的預設。
    #
    # [2026-08-01] 曾經改成自動跳到第一起事件前 10 分鐘（因為資料 17:00 起、
    # 最早事件 22:00，從頭播要等很久才有事件可注入）。使用者明確要求拿掉——
    # 他要自己拉時間軸決定看哪一段，系統不該替他挑起點。
    # 需要快轉就拉滑桿（`POST /api/simulation/seek`）。
    _simulation_state["current_time"] = start_time
    _simulation_state["speed"] = body.get("speed", 60)  # 預設 1 秒跑 1 分鐘
    _simulation_state["playing"] = False
    _simulation_state["last_level"] = None
    
    # 重設後端狀態
    orchestrator.reset()
    global _last_traffic_level
    _last_traffic_level = None
    
    # 推播初始狀態。讀 `_simulation_state` 的實際值而不是再寫一次 `start_time`：
    # 兩者目前相同，但只要有人動了起播邏輯，這裡就會自動跟上，
    # 不會出現「時鐘顯示一個時間、事件列表用另一個時間去查」的矛盾畫面。
    cursor = _simulation_state["current_time"]
    await ws_manager.broadcast({
        "message_type": "simulation.state.v1",
        "payload": {
            "action": "started",
            "current_time": cursor.isoformat(),
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
        }
    })

    return {"status": "ok", "message": "模擬器已啟動", "current_time": cursor.isoformat()}


@app.post("/api/simulation/play")
async def play_simulation():
    """開始播放"""
    if not _simulation_state["enabled"]:
        return {"status": "error", "message": "模擬器尚未啟動"}
    
    _simulation_state["playing"] = True
    
    await ws_manager.broadcast({
        "message_type": "simulation.state.v1",
        "payload": {"action": "playing"}
    })
    
    return {"status": "ok", "message": "開始播放"}


@app.post("/api/simulation/pause")
async def pause_simulation():
    """暫停播放"""
    _simulation_state["playing"] = False
    
    await ws_manager.broadcast({
        "message_type": "simulation.state.v1",
        "payload": {"action": "paused"}
    })
    
    return {"status": "ok", "message": "已暫停"}


@app.post("/api/simulation/reset")
async def reset_simulation():
    """重置模擬器"""
    if _simulation_state["start_time"]:
        _simulation_state["current_time"] = _simulation_state["start_time"]
        _simulation_state["playing"] = False
        _simulation_state["last_level"] = None
        
        orchestrator.reset()
        global _last_traffic_level
        _last_traffic_level = None
        
        await ws_manager.broadcast({
            "message_type": "simulation.state.v1",
            "payload": {
                "action": "reset",
                "current_time": _simulation_state["start_time"].isoformat()
            }
        })
    
    return {"status": "ok", "message": "已重置"}


@app.post("/api/simulation/stop")
async def stop_simulation():
    """停止模擬器"""
    _simulation_state["enabled"] = False
    _simulation_state["playing"] = False
    _simulation_state["current_time"] = None
    
    await ws_manager.broadcast({
        "message_type": "simulation.state.v1",
        "payload": {"action": "stopped"}
    })
    
    return {"status": "ok", "message": "模擬器已停止"}


@app.post("/api/simulation/seek")
async def seek_simulation(body: dict):
    """跳到指定時間"""
    if not _simulation_state["enabled"]:
        return {"status": "error", "message": "模擬器尚未啟動"}
    
    time_str = body.get("time")
    if not time_str:
        return {"status": "error", "message": "time 為必填"}
    
    try:
        # 解析時間（支援 HH:MM 格式）
        if len(time_str) == 5 and ":" in time_str:
            # HH:MM 格式，補上日期
            base_date = _simulation_state["start_time"].date()
            hour, minute = map(int, time_str.split(":"))
            new_time = datetime(base_date.year, base_date.month, base_date.day, hour, minute, tzinfo=_TZ_TAIPEI)
        else:
            new_time = datetime.fromisoformat(time_str)
            if new_time.tzinfo is None:
                new_time = new_time.replace(tzinfo=_TZ_TAIPEI)
        
        _simulation_state["current_time"] = new_time
        
        await ws_manager.broadcast({
            "message_type": "simulation.state.v1",
            "payload": {
                "action": "seeked",
                "current_time": new_time.isoformat()
            }
        })
        
        return {"status": "ok", "current_time": new_time.isoformat()}
    except Exception as e:
        return {"status": "error", "message": f"時間格式錯誤: {e}"}


# 模擬事件生成器配置
_SIM_EVENT_COUNTER = 0

_EVENT_TYPES = [
    {
        "type": "Traffic_Accident",
        "severities": ["Critical", "High", "Medium"],
        "statuses": ["Closed", "Restricted"],
        "descriptions": [
            "多車追撞事故，現場封閉處理中",
            "機車與行人擦撞，救護車到場處理",
            "公車與小客車碰撞，佔用車道",
            "計程車拋錨阻塞車道",
        ],
    },
    {
        "type": "Road_Collapse_Accident",
        "severities": ["Critical", "High"],
        "statuses": ["Closed"],
        "descriptions": [
            "路面塌陷，全線封閉搶修中",
            "地下管線破裂導致路面下陷",
            "大型坑洞出現，車輛無法通行",
        ],
    },
    {
        "type": "Crowd_Surge_Injury",
        "severities": ["High", "Medium"],
        "statuses": ["Restricted", "Caution"],
        "descriptions": [
            "大量人潮聚集造成推擠，有民眾受傷",
            "活動散場人流過大，需進行分流管制",
            "跨年人群擁擠，啟動疏散機制",
        ],
    },
    {
        "type": "Power_Failure",
        "severities": ["Medium", "High"],
        "statuses": ["Caution", "Restricted"],
        "descriptions": [
            "區域停電導致號誌失效，需人工指揮",
            "交通號誌故障閃爍，車流混亂",
            "路燈全滅，能見度不佳",
        ],
    },
    {
        "type": "Vehicle_Fire",
        "severities": ["Critical", "High"],
        "statuses": ["Closed", "Restricted"],
        "descriptions": [
            "車輛自燃，消防隊到場灌救中",
            "貨車起火，現場濃煙瀰漫",
            "機車電池爆炸起火",
        ],
    },
    {
        "type": "Water_Main_Break",
        "severities": ["Medium", "High"],
        "statuses": ["Restricted", "Caution"],
        "descriptions": [
            "自來水管爆裂，路面積水",
            "消防栓破裂，大量湧水影響通行",
        ],
    },
    {
        "type": "Debris_On_Road",
        "severities": ["Medium", "Low"],
        "statuses": ["Caution"],
        "descriptions": [
            "貨車掉落物散落路面，清理中",
            "工地建材掉落阻塞車道",
            "路樹倒塌佔用部分車道",
        ],
    },
]


@app.post("/api/incidents/generate")
async def generate_incident():
    """模擬事件生成器：隨機產生一筆新事件並執行決策流程。"""
    import random
    from datetime import datetime, timezone, timedelta

    global _SIM_EVENT_COUNTER
    _SIM_EVENT_COUNTER += 1

    tz = timezone(timedelta(hours=8))
    
    # 載入路網資料取得路段資訊
    bundle = orchestrator.GATEWAY.load_data()
    road_segments = [r for r in bundle.road_network if r.segment_id.startswith("RD_")]
    
    if not road_segments:
        return JSONResponse(status_code=200, content={
            "status": "error",
            "errors": [{"code": "INTERNAL_ERROR", "message": "無可用路段資料"}],
        })

    # 事件發生時刻。
    #
    # [2026-08-02] 模擬器在跑的時候，事件就發生在**畫面上的那一刻**。
    # 原本一律在資料時間範圍內隨機挑一個時間點，於是模擬器停在 22:10、
    # 按下產生事件，事件卻標成 19:47——路況、ETE、建議書全部算在那個時刻，
    # 而畫面上顯示的是 22:10。使用者看到的是兩套對不起來的數字。
    #
    # 隨機挑時間這個行為本身是有理由的（真實時間落在資料範圍外，as-of 查詢
    # 會拿到邊界值），所以模擬器沒在跑時保留原邏輯當退路。
    traffic_timestamps = [t.timestamp for t in bundle.traffic]
    sim_time = clock.simulation_time()
    if sim_time is not None:
        event_time = sim_time
    elif traffic_timestamps:
        min_ts = min(traffic_timestamps)
        max_ts = max(traffic_timestamps)
        # 在資料範圍內隨機選一個時間點
        delta_seconds = int((max_ts - min_ts).total_seconds())
        random_offset = random.randint(0, max(1, delta_seconds))
        event_time = min_ts + timedelta(seconds=random_offset)
    else:
        event_time = clock.now()

    # 隨機選擇事件類型
    event_config = random.choice(_EVENT_TYPES)
    
    # 隨機選擇路段
    road = random.choice(road_segments)
    
    # 隨機選擇嚴重度和狀態
    severity = random.choice(event_config["severities"])
    status = random.choice(event_config["statuses"])
    description_template = random.choice(event_config["descriptions"])
    
    # 組成事件 ID
    event_id = f"TPE_2026_SIM_{_SIM_EVENT_COUNTER:03d}"
    
    # 組成位置描述
    location = f"{road.name}"
    if road.intersections:
        intersection = random.choice(road.intersections)
        location = f"{road.name}與{intersection}路口"
    
    # 組成完整描述
    description = f"{event_time.strftime('%Y-%m-%d %H:%M')} {location} {description_template}"
    
    # 建立 Incident 物件
    from src.models import Incident, IncidentSeverity
    
    severity_enum = IncidentSeverity(severity)
    
    incident = Incident(
        event_id=event_id,
        type=event_config["type"],
        location=location,
        affected_segment=road.segment_id,
        affected_road=road.segment_id,  # 對於模擬事件，affected_road = affected_segment
        status=status,
        severity=severity_enum,
        description=description,
        timestamp=event_time,
    )

    # 廣播決策週期開始
    await ws_manager.broadcast({
        "message_type": "decision.cycle_start.v1",
        "payload": {"triggered_by": [event_id]},
    })

    # 執行決策流程（同上：決策期間暫停模擬時鐘）
    with _hold_simulation_clock():
        decision_result = await orchestrator.handle_incident(incident, ws_broadcaster=ws_manager.broadcast)
    payload_json = decision_result.model_dump(mode="json")

    # 廣播警報
    await ws_manager.broadcast({
        "message_type": "decision.alert.v1",
        "payload": {
            "level": decision_result.level,
            "severity": incident.severity.value,
            "description": incident.description,
            "ete_minutes": decision_result.ete.minutes if decision_result.ete else None,
        },
    })

    # ★ 情境3：檢查是否為「無可用替代路線」的嚴重情況
    # 同上：候選全數飽和（all_alternatives_saturated）與完全找不到候選
    # （no_feasible_route）對指揮官是同一件事——沒有路可以替補。
    if decision_result.routes and (
        decision_result.routes.no_feasible_route
        or decision_result.routes.all_alternatives_saturated
    ):
        _saturated_only = not decision_result.routes.no_feasible_route
        await ws_manager.broadcast({
            "message_type": "decision.alert.v1",
            "payload": {
                "level": "A",
                "severity": "Critical",
                "description": (
                    f"⚠️ 嚴重警告：{incident.location} 周邊候選路段全數飽和，已無可替補路段！"
                    if _saturated_only
                    else f"⚠️ 嚴重警告：{incident.location} 附近已無可用替代路線！"
                ),
                "ete_minutes": None,
                "alert_type": "NO_FEASIBLE_ROUTE",
            },
        })

    # ★ 情境2：檢查是否影響其他活躍事件的替代路線（連鎖衝突）
    await _check_cascade_impact(incident)

    # 廣播決策完成
    await ws_manager.broadcast({
        "message_type": "decision.completed.v1",
        "payload": payload_json,
    })

    # 廣播 Dashboard 更新
    await ws_manager.broadcast({
        "message_type": "dashboard.updated.v1",
        "payload": {"event_id": event_id, "level": decision_result.level},
    })

    return JSONResponse(content={
        "status": "ok",
        "message_type": "decision.completed.v1",
        "payload": payload_json,
    })


@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    """單向推播，收到的內容大部分丟棄。
    例外：chat.clear_session.v1 會真的處理（W2 session 清除）。
    """
    await ws_manager.connect(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            # 嘗試解析 clear_session
            try:
                import json
                msg = json.loads(raw)
                if msg.get("message_type") == "chat.clear_session.v1":
                    session_id = msg.get("payload", {}).get("session_id")
                    if session_id:
                        from src.session.session_manager import clear_session
                        clear_session(session_id)
                        await websocket.send_json({
                            "message_type": "chat.session_cleared.v1",
                            "payload": {"session_id": session_id},
                        })
            except (json.JSONDecodeError, KeyError):
                pass  # 非 JSON 或格式不對，丟棄
    except WebSocketDisconnect:
        ws_manager.disconnect(websocket)



if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
