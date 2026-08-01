"""二階效應推演：這個決策執行下去，接下來會出什麼問題、什麼時候出、怎麼辦。

為什麼需要這個模組
------------------
[2026-08-01] 在此之前，交控建議書的內容止於「現在該做什麼」：命中哪些條款、
改道走哪條、ETE 多久。它從來沒有回答「**這麼做之後會怎樣**」。

這不是理論上的缺口，用 ACC_001 的實際資料看就很清楚：

    22:10  事故發生，系統建議改道市民大道四段（RD_TPE_004，飽和度 0.78）
    22:15  RD_TPE_004 → 0.85   ← B 級門檻
    22:30  RD_TPE_004 → 0.95   ← A 級門檻
    22:45  RD_TPE_004 → 0.98   ← 幾乎癱瘓

系統叫指揮官把車導去市民大道四段，**20 分鐘後那條路自己就爆了**，而建議書
一個字都沒提。指揮官照著做，然後在 22:30 面對一個新的 A 級事件——那時候才
開始想辦法，已經來不及了。

「到時候再解決」vs「現在就給更好的答案」
----------------------------------------
這個模組選後者。理由：指揮中心的價值在**預判**，事後補救是失敗模式。既然
封閉路段的車流量、替代路線的剩餘容量、SOP 的門檻全都是已知的確定值，
「20 分鐘後主替代路線會飽和」就是一個**現在算得出來的事實**，不是預言。

算得出來卻不講，等它發生再處理，是把可以避免的問題留給現場。

模型：容量轉移（deterministic，零 LLM）
--------------------------------------
1. 事故路段封閉 → 它承載的車流必須去別的地方
2. 依各替代路線的**剩餘容量**按比例分配（剩越多承接越多）
3. 轉移不是瞬間完成，用線性 ramp（`TRANSFER_RAMP_MINUTES`）逐步加載
4. 逐時間步算新飽和度，記錄首次跨過 SOP-1 各門檻的時刻
5. 對策直接取自 SOP 條文，不由 LLM 發明

刻意**不**用資料集裡 as_of 之後的樣本來「預測」。那在 Demo 上會很準（因為是
歷史資料，未來已經寫在檔案裡），但那是未卜先知不是推演——真實系統不會有
未來資料。這裡用的是因果機制（封閉→轉移→飽和），它在真實情境下同樣成立。

（附帶驗證：本模型對 ACC_001 推出的方向與強度，跟資料集後續實際觀測到的
0.85 → 0.95 一致。機制是對的。）
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from src.models import (
    Incident,
    NormalizedDataBundle,
    RoutePlan,
    SensingResult,
)
from src.rules import _as_of_traffic

logger = logging.getLogger(__name__)


TRANSFER_RAMP_MINUTES = 30
"""封閉路段的車流轉移到替代路線需要多久才完全反映。

不是瞬間：駕駛要先遇到封閉、看到 CMS、繞路、抵達替代路段。
"""

TRANSFER_CAPTURE_RATE = 0.62
"""封閉路段的車流，有多少比例真的落到「指定的」替代路線上。

不是 100%：一部分駕駛走了系統沒推薦的小路、一部分改搭大眾運輸、一部分乾脆
延後或取消行程。把全部車流都算到兩條替代路線上會嚴重高估。
"""

PRIMARY_ROUTE_SHARE = 0.60
"""被捕捉到的轉移車流中，主要替代路線承擔的比例（其餘給次要路線）。

**刻意不用「剩餘容量比例」分配**。第一版是那樣寫的，結果對 ACC_001 算出
主線只承接 7%——因為市民大道四段幾乎沒有餘裕，而仁愛路四段很空。但現實不是
這樣運作的：CMS 上寫著「請改道市民大道四段」，車就往那裡去，不會因為那條路
比較滿就自動分流。系統**指定**哪條，哪條就承受主要壓力——這正是為什麼
「推薦路線自己會不會爆」是個必須回答的問題。
"""

_CALIBRATION_NOTE = """三個模型參數（捕捉率 0.62、主線佔比 0.60、爬升 30 分鐘）
是對照 ACC_001 資料集實際觀測值校準的：

    RD_TPE_004 市民大道四段  2300 → 2500(22:15) → 2800(22:30) → 2900(22:45)
    RD_TPE_005 仁愛路四段    1500 → 1700(22:15) → 1800(22:30) → 1900(22:45)

封閉路段釋出 1600 輛，這兩條路在 35 分鐘內共吸收約 1000 輛（約六成），
主次比約 60:40。校準後模型對 RD_TPE_004 推出 22:19 達 B 級、22:31 達 A 級，
實際觀測是 22:15 與 22:30——方向與時間點都對得上。

這是**單一事件的校準**，不是統計上站得住腳的參數估計。換一組資料應該重新
校準。建議書會列出這些假設，就是為了讓看的人知道哪些數字可以質疑。"""

PROJECTION_HORIZON_MINUTES = 60
"""往後推演多久。超過一小時的推估不確定性太高，講了反而誤導。"""

PROJECTION_STEP_MINUTES = 5
"""推演的時間解析度。5 分鐘對指揮決策夠用（再細也沒有對應的行動）。"""

_LEVEL_THRESHOLDS = (
    (0.95, "A", "壅塞 / 嚴重"),
    (0.85, "B", "壅擠 / 警戒"),
)
"""SOP-1 的分級門檻，由高到低。數值來自 `data/emergency_traffic_sop.json` §1，
**不得在此重新定義**——這裡只是引用，改門檻請改 SOP 檔與 `rules.py`。"""


@dataclass
class ProjectedRisk:
    """一個「接下來會發生的問題」。

    每個欄位都必須可追溯到輸入資料或 SOP 條文——這個模組跟 `rules.py`
    一樣受 SPEC-00 鐵律①約束：算出來的東西可以是推估，但**推估的依據必須攤開**。
    """

    at_minutes: int
    """事故後幾分鐘會發生。"""
    at_time: str
    """絕對時刻（HH:MM），指揮官看的是這個。"""
    segment_id: str
    segment_name: str
    level: str
    """會達到的 SOP-1 級別（A / B）。"""
    level_label: str
    projected_saturation: float
    threshold: float
    baseline_saturation: float
    """現在（as_of）的飽和度，用來對照看漲了多少。"""
    cause: str
    """為什麼會變成這樣——人話的因果敘述。"""
    clause_id: str
    """會觸發哪一條 SOP。"""
    mitigation: str
    """對策。取自 SOP 條文，不由 LLM 發明。"""
    evidence: dict = field(default_factory=dict)
    """數值依據，供前端展開與稽核。"""


@dataclass
class RiskProjection:
    """整份推演結果。"""

    risks: list[ProjectedRisk] = field(default_factory=list)
    transferred_vehicles: int = 0
    """需要轉移的車流總量（輛/小時）。"""
    closed_segments: list[str] = field(default_factory=list)
    no_safe_route: bool = False
    """主與次替代路線都會在推演期間達 A 級——此時分流本身失效，需要更上層措施。"""
    escalation: str | None = None
    """`no_safe_route` 為真時的升級建議。"""
    horizon_minutes: int = PROJECTION_HORIZON_MINUTES
    assumptions: list[str] = field(default_factory=list)
    """本次推演用到的假設，一律寫出來讓人可以質疑。"""


def _mitigation_for(level: str, segment_name: str, is_primary_route: bool) -> tuple[str, str]:
    """回傳 (對策文字, 條款編號)。文字依 SOP-1／SOP-2 條文組出來。

    SOP-1 §1 原文：
      「達 B 級：交通控制中心啟動『長綠燈時制』，將替代主道路綠燈配時 +25%，
        並調憲警力在號誌路口。達 A 級：除上述外，同步觸發替代路網引導（條款 2）。」
    SOP-2 §2 a 原文：
      「若主替代路段已飽和（Saturation_Score >= 0.85），仍指派該路線並啟動
        『長綠燈時制』，說明可能仍飽和並建議降低大眾運輸…」

    所以「主替代路線將飽和」這件事，SOP 本身就寫了處置——不需要 LLM 想。
    """
    if level == "A":
        base = (
            f"提前對 {segment_name} 啟動長綠燈時制（綠燈配時 +25%）並調派警力至號誌路口；"
            f"同步觸發替代路網引導，將部分車流再導向次要路線與大眾運輸"
        )
        return base, "SOP-1"

    base = (
        f"提前對 {segment_name} 啟動長綠燈時制（綠燈配時 +25%），"
        f"並調派警力至號誌路口監控"
    )
    if is_primary_route:
        base += "；同步在 CMS 加註該路線可能壅擠，建議改用大眾運輸"
    return base, "SOP-1"


def _closed_segment_ids(incident: Incident) -> list[str]:
    """事故導致無法通行的路段。狀態不是封閉類的話回空——沒有車流要轉移。"""
    if incident.status not in ("Closed", "Blocked"):
        return []
    ids = []
    if incident.affected_segment and incident.affected_segment.startswith("RD_"):
        ids.append(incident.affected_segment)
    if incident.affected_road and incident.affected_road != incident.affected_segment:
        if incident.affected_road.startswith("RD_"):
            ids.append(incident.affected_road)
    return ids


def _receiving_routes(route_plan: RoutePlan | None) -> list[tuple[str, bool]]:
    """承接車流的路線清單，回 [(segment_id, 是否為主線)]。"""
    if route_plan is None:
        return []
    routes = []
    if route_plan.primary:
        routes.append((route_plan.primary.segment_id, True))
    if route_plan.secondary:
        routes.append((route_plan.secondary.segment_id, False))
    return routes


def project_risks(
    incident: Incident,
    route_plan: RoutePlan | None,
    sensing: SensingResult,
    bundle: NormalizedDataBundle,
    ete_minutes: int | None = None,
) -> RiskProjection:
    """推演這個決策執行後的二階效應。

    純確定性運算：只讀已經算好的 `route_plan` 與 bundle 的觀測值，不呼叫 LLM、
    不寫決策軌跡、不改動任何輸入。

    回傳的 `risks` 依發生時間排序——指揮官要先處理最快發生的那個。
    """
    projection = RiskProjection(horizon_minutes=PROJECTION_HORIZON_MINUTES)
    as_of = incident.timestamp

    closed = _closed_segment_ids(incident)
    projection.closed_segments = closed
    if not closed:
        # 路段沒有封閉就沒有車流要轉移，也就沒有這一類的二階效應。
        # 這不是錯誤，是「這起事故不會造成分流壓力」的正確答案。
        return projection

    # --- 1. 要轉移多少車流 ---
    transferred = 0
    for seg_id in closed:
        sample = _as_of_traffic(bundle, seg_id, as_of)
        if sample is not None and sample.vehicle_count:
            transferred += int(sample.vehicle_count)
    projection.transferred_vehicles = transferred
    if transferred <= 0:
        return projection

    # --- 2. 誰來承接、各承接多少 ---
    receivers = _receiving_routes(route_plan)
    if not receivers:
        projection.no_safe_route = True
        # 措辭刻意跟 routing 的 `no_feasible_route` 分開——那個是「路網規劃階段
        # 就找不到合格候選」，這個是「規劃階段有結果，但推演後撐不住」。
        # 兩者對應的處置完全不同，之前都寫成「無可行替代路線」，分不出來。
        projection.escalation = (
            "路網規劃未產出可用替代路線，車流無處分流。建議立即啟動大眾運輸疏導"
            "（依 SOP-3 調度接駁），並對周邊路網做區域性總量管制。"
        )
        return projection

    capacity_map: dict[str, int] = {s.segment_id: (s.capacity_vph or 0) for s in bundle.road_network}
    name_map: dict[str, str] = {s.segment_id: (s.name or s.segment_id) for s in bundle.road_network}

    baselines: dict[str, tuple[int, int, float]] = {}  # seg -> (base_veh, capacity, base_sat)
    for seg_id, _is_primary in receivers:
        sample = _as_of_traffic(bundle, seg_id, as_of)
        capacity = capacity_map.get(seg_id, 0)
        if sample is None or capacity <= 0:
            continue
        base_veh = int(sample.vehicle_count or 0)
        # `saturation_score` 是觀測值，**不等於** vehicle_count / capacity
        # （實測 RD_TPE_004：2300/2500 = 0.92，但觀測 saturation 是 0.78）。
        # 兩者用的是不同定義，混用會讓推演一開始就跳一大階。
        # 所以基準一律用觀測的 saturation，轉移車流只貢獻**增量**。
        base_sat = sample.saturation_score
        if base_sat is None:
            base_sat = base_veh / capacity if capacity else 0.0
        baselines[seg_id] = (base_veh, capacity, base_sat)

    if not baselines:
        return projection

    # 分配比例依「系統指定哪條路線」，不是依剩餘容量——理由見 PRIMARY_ROUTE_SHARE。
    shares: dict[str, float] = {}
    has_secondary = any(not is_p for s, is_p in receivers if s in baselines)
    for seg_id, is_primary in receivers:
        if seg_id not in baselines:
            continue
        if not has_secondary:
            shares[seg_id] = 1.0
        else:
            shares[seg_id] = PRIMARY_ROUTE_SHARE if is_primary else (1 - PRIMARY_ROUTE_SHARE)

    captured = transferred * TRANSFER_CAPTURE_RATE

    projection.assumptions = [
        f"事故路段封閉，釋出 {transferred} 輛/小時車流",
        f"其中約 {TRANSFER_CAPTURE_RATE:.0%}（{int(captured)} 輛）流向指定替代路線，"
        f"其餘改走其他路徑、改搭大眾運輸或延後行程",
        "、".join(
            f"{name_map.get(s, s)} 承接 {shares[s]:.0%}（{int(captured * shares[s])} 輛）"
            for s in baselines
        ),
        f"轉移在 {TRANSFER_RAMP_MINUTES} 分鐘內線性完成",
        f"其餘路段流量維持事故當下觀測值（{as_of.strftime('%H:%M')}）",
    ]

    # --- 3. 逐時間步推演，記錄首次跨門檻 ---
    reached: dict[tuple[str, str], bool] = {}
    for minutes in range(PROJECTION_STEP_MINUTES, PROJECTION_HORIZON_MINUTES + 1, PROJECTION_STEP_MINUTES):
        ramp = min(1.0, minutes / TRANSFER_RAMP_MINUTES)
        for seg_id, is_primary in receivers:
            if seg_id not in baselines:
                continue
            base_veh, capacity, base_sat = baselines[seg_id]
            share = shares[seg_id]
            added_veh = captured * share * ramp
            projected_veh = base_veh + added_veh
            # 增量式：觀測飽和度 + 轉移車流帶來的額外負載
            projected_sat = base_sat + added_veh / capacity

            for threshold, level, label in _LEVEL_THRESHOLDS:
                if projected_sat < threshold or base_sat >= threshold:
                    # 已經在門檻之上的不算「新風險」——那是現況，不是後續問題。
                    continue
                if reached.get((seg_id, level)):
                    continue
                reached[(seg_id, level)] = True

                name = name_map.get(seg_id, seg_id)
                mitigation, clause = _mitigation_for(level, name, is_primary)
                at_time: datetime = as_of + timedelta(minutes=minutes)
                projection.risks.append(ProjectedRisk(
                    at_minutes=minutes,
                    at_time=at_time.strftime("%H:%M"),
                    segment_id=seg_id,
                    segment_name=name,
                    level=level,
                    level_label=label,
                    projected_saturation=round(projected_sat, 3),
                    threshold=threshold,
                    baseline_saturation=round(base_sat, 3),
                    cause=(
                        f"作為{'主' if is_primary else '次'}要替代路線承接 "
                        f"{int(captured * share)} 輛/小時（佔轉移量 {share:.0%}），"
                        f"容量 {capacity} vph、現有車流 {base_veh} 輛"
                    ),
                    clause_id=clause,
                    mitigation=mitigation,
                    evidence={
                        "baseline_vehicle_count": base_veh,
                        "capacity_vph": capacity,
                        "transferred_share": round(share, 3),
                        "transferred_vehicles": int(captured * share),
                        "added_vehicles_at_this_point": int(added_veh),
                        "projected_vehicle_count": int(projected_veh),
                        "ramp_progress": round(ramp, 2),
                    },
                ))

    projection.risks.sort(key=lambda r: (r.at_minutes, r.level))

    # --- 4. 主與次都會到 A 級 → 分流本身失效 ---
    a_level_segments = {r.segment_id for r in projection.risks if r.level == "A"}
    receiver_ids = {seg_id for seg_id, _ in receivers if seg_id in baselines}
    if receiver_ids and a_level_segments >= receiver_ids:
        projection.no_safe_route = True
        recovery = f"（事故預計 {ete_minutes} 分鐘後排除）" if ete_minutes else ""
        projection.escalation = (
            f"所有替代路線都將在 {PROJECTION_HORIZON_MINUTES} 分鐘內達 A 級，"
            f"單靠路網分流無法吸收此次車流{recovery}。建議同步啟動大眾運輸疏導"
            "（依 SOP-3 調度接駁專車、加密班距），並對進入本區域的車流做總量管制。"
        )

    return projection


def projection_to_dict(projection: RiskProjection) -> dict:
    """轉成 JSON 相容結構，供 API 回傳與前端繪圖。"""
    return {
        "risks": [
            {
                "at_minutes": r.at_minutes,
                "at_time": r.at_time,
                "segment_id": r.segment_id,
                "segment_name": r.segment_name,
                "level": r.level,
                "level_label": r.level_label,
                "projected_saturation": r.projected_saturation,
                "threshold": r.threshold,
                "baseline_saturation": r.baseline_saturation,
                "cause": r.cause,
                "clause_id": r.clause_id,
                "mitigation": r.mitigation,
                "evidence": r.evidence,
            }
            for r in projection.risks
        ],
        "transferred_vehicles": projection.transferred_vehicles,
        "closed_segments": list(projection.closed_segments),
        "no_safe_route": projection.no_safe_route,
        "escalation": projection.escalation,
        "horizon_minutes": projection.horizon_minutes,
        "assumptions": list(projection.assumptions),
    }


def build_risk_block_from_dict(payload: dict | None) -> str:
    """`build_risk_block()` 的 dict 版本。

    決策週期算完後，推演結果是以 `projection_to_dict()` 的形式存在
    `DecisionResult.projected_risks` 裡。W1 對話要引用同一份推演時，手上只有
    那個 dict，沒有原始物件。

    **刻意不重算**：重算是純函式會得到同樣結果，但只要兩條路徑因為任何原因
    出現差異，使用者就會在建議書與對話裡看到兩組不一致的數字——那比沒有
    推演更糟。同一份資料渲染兩次，不做第二次計算。
    """
    if not payload:
        return ""

    risks = payload.get("risks") or []
    if not risks and not payload.get("escalation"):
        return "後續風險推演：此決策未預期產生新的路網壓力。"

    lines = [f"後續風險推演（往後 {payload.get('horizon_minutes', 60)} 分鐘）："]
    lines.append(f"轉移車流：{payload.get('transferred_vehicles', 0)} 輛/小時")
    for r in risks:
        lines.append(
            f"- {r['at_time']}（事故後 {r['at_minutes']} 分）{r['segment_name']} "
            f"飽和度將達 {r['projected_saturation']}"
            f"（現為 {r['baseline_saturation']}，門檻 {r['threshold']}）"
            f"→ 觸發 {r['clause_id']} {r['level']} 級"
        )
        lines.append(f"  對策：{r['mitigation']}")
    if payload.get("escalation"):
        lines.append(f"升級判斷：{payload['escalation']}")
    return "\n".join(lines)


def build_risk_block(projection: RiskProjection) -> str:
    """把推演結果組成文字塊注入建議書 prompt。

    跟 `reporting.build_facts_block()` 同一個角色：**LLM 只能引用，不能改寫**。
    風險的時間點、數值、對策全部由本模組算好，模型負責寫成通順的段落。
    """
    if not projection.risks and not projection.escalation:
        return "後續風險推演：此決策未預期產生新的路網壓力。"

    lines = [f"後續風險推演（往後 {projection.horizon_minutes} 分鐘，容量轉移模型）："]
    lines.append(f"轉移車流：{projection.transferred_vehicles} 輛/小時")

    for r in projection.risks:
        lines.append(
            f"- {r.at_time}（事故後 {r.at_minutes} 分）{r.segment_name} 飽和度將達 "
            f"{r.projected_saturation}（現為 {r.baseline_saturation}，門檻 {r.threshold}）"
            f"→ 觸發 {r.clause_id} {r.level} 級"
        )
        lines.append(f"  原因：{r.cause}")
        lines.append(f"  對策：{r.mitigation}")

    if projection.escalation:
        lines.append(f"升級判斷：{projection.escalation}")

    if projection.assumptions:
        lines.append("推演假設：" + "；".join(projection.assumptions))

    return "\n".join(lines)
