"""A3 ETE 計算 + C1-C4 建議書/號誌/聯動/簡訊生成。

參考 spec：`.kiro/specs/m4-decision-reporting/requirements.md`（唯一權威，含 ETE
公式、三筆黃金驗收值、C1-C4 提示詞契約、失敗降級規則）。**這不是**
`m4-explanation-chain-and-orchestrator/`（那是解釋鏈/Orchestrator 核心邏輯，
命名雖然都帶「模組四」但範圍不同，見該資料夾與本檔案的分工說明）。

C1~C4 一律由 A2 編排觸發，本模組不得被繞過直接呼叫（01-module-boundaries.md 規則9）。
"""

from __future__ import annotations

import logging
from datetime import timedelta
from pathlib import Path

from src.models import (
    BedrockAdvisory,
    EteEstimate,
    Incident,
    Notification,
    NormalizedDataBundle,
    RoutePlan,
    SensingResult,
)
from src.rules import get_saturation

logger = logging.getLogger(__name__)

_BASE_CLEARANCE = {
    "Critical": 60,
    "High": 40,
    "Medium": 20,
    "Low": 20,
}


def calculate_ete(incident: Incident, bundle: NormalizedDataBundle) -> EteEstimate:
    """A3：確定性 ETE 計算，唯一公式來源。

    取值順序：有 affected_road 用它，否則用 RD 類 affected_segment；
    多條才取平均（目前三筆事件都只有一條）。
    """
    base = _BASE_CLEARANCE.get(incident.severity.value)
    if base is None:
        raise ValueError(f"未知 severity: {incident.severity.value}")

    # 決定受影響路段
    target_segments: list[str] = []
    if incident.affected_road:
        target_segments.append(incident.affected_road)
    elif incident.affected_segment.startswith("RD_"):
        target_segments.append(incident.affected_segment)

    # 取 as-of 飽和度
    saturations: list[float] = []
    for seg_id in target_segments:
        sat = get_saturation(bundle, seg_id, incident.timestamp)
        if sat is not None:
            saturations.append(sat)

    if not saturations:
        # 沒有飽和度資料，congestion penalty = 0
        avg_sat = 0.5
    else:
        avg_sat = sum(saturations) / len(saturations)

    # 公式
    congestion_penalty = max(0, (avg_sat - 0.5) * 60)
    minutes = int(base + congestion_penalty)

    # recovery_at
    recovery_dt = incident.timestamp + timedelta(minutes=minutes)
    recovery_at = recovery_dt.strftime("%Y-%m-%d %H:%M")

    # formula 文字
    formula = f"{base} + max(0,({avg_sat}-0.5)*60) = {minutes}"

    return EteEstimate(
        minutes=minutes,
        recovery_at=recovery_at,
        formula=formula,
        base_clearance=base,
        average_saturation=avg_sat,
    )


def _load_prompt(filename: str) -> str:
    """從 prompts/ 目錄讀取提示詞檔案。"""
    path = Path(__file__).resolve().parents[1] / "prompts" / filename
    return path.read_text(encoding="utf-8")


def build_facts_block(
    incident: Incident,
    sensing: SensingResult,
    route_plan: RoutePlan | None,
    ete: EteEstimate,
    bundle: NormalizedDataBundle | None = None,
) -> str:
    """把確定性事實組成文字塊注入 prompt，LLM 只能引用不能改寫。

    [2026-08-01 改為公開 API]
    原本是 `_build_facts_block`，只有 C1-C3 建議書在用。現在 W1 What-if Agent
    也要引用同一份事實（見 `agent/whatif_agent.py` 的「方案A：共用事實管線」），
    所以改成公開。

    **這是 SPEC-00 鐵律①「LLM 只表達、不改寫」的實際落點**：建議書、What-if
    對話、What-if 情境建議書三處的數字必然一致，因為全部來自這一個函式。
    如果哪天有人想再寫一份「類似的」事實組裝，那就是在製造第二個真相來源——
    要加欄位請加在這裡。
    """
    lines = [
        f"事件ID: {incident.event_id}",
        f"位置: {incident.location}",
        f"類型: {incident.type}",
        f"狀態: {incident.status}",
        f"嚴重度: {incident.severity.value}",
        f"交通等級: {sensing.traffic_level}",
        f"ETE: {ete.minutes} 分鐘",
        f"預計恢復時間: {ete.recovery_at}",
        f"命中SOP條款: {', '.join(sorted({h.clause_id for h in sensing.rule_hits}))}",
    ]

    if route_plan and route_plan.primary:
        lines.append(f"主要替代路線: {route_plan.primary.name} ({route_plan.primary.segment_id})")
    if route_plan and route_plan.secondary:
        lines.append(f"次要替代路線: {route_plan.secondary.name} ({route_plan.secondary.segment_id})")
    if route_plan:
        for exc in route_plan.excluded:
            reason_text = _reason_code_to_text(exc.reason_code, exc)
            lines.append(f"排除路段: {exc.name} — {reason_text}")

    # SOP-5 警力人數（需要 bundle 算 count_affected_intersections）
    sop5_hits = [h for h in sensing.rule_hits if h.clause_id == "SOP-5"]
    if sop5_hits and bundle is not None:
        from src.routing import count_affected_intersections
        intersection_count = count_affected_intersections(bundle, incident.affected_segment)
        police_personnel = intersection_count * 2
        lines.append(f"SOP-5 受影響路口數: {intersection_count}")
        lines.append(f"SOP-5 建議警力人數: {police_personnel} 人")

    return "\n".join(lines)


def _reason_code_to_text(code: str | None, candidate) -> str:
    """把 ReasonCode 轉成人話，供建議書引用。"""
    mapping = {
        "CLOSED": "事故封閉路段",
        "CAPACITY_INSUFFICIENT": f"容量不足（{candidate.capacity_vph} < 1000）",
        "NOT_IN_ALTERNATIVES": "非替代路線候選",
        "NOT_DIRECTLY_INTERSECTING": "與事故路段無直接交會",
        "DOWNSTREAM_ONLY": "僅位於下游",
        "FLOW_DIRECTION_MISMATCH": "流向不符",
        "SATURATED": f"已飽和（飽和度 {candidate.saturation_score}）",
        "UNKNOWN_SEGMENT": "未知路段",
        "MISSING_TRAFFIC_SNAPSHOT": "缺少車流快照",
    }
    return mapping.get(code, code or "未知原因")


def _generate_c1_c3_fallback(
    incident: Incident,
    sensing: SensingResult,
    route_plan: RoutePlan | None,
    ete: EteEstimate,
    bundle: NormalizedDataBundle,
    merged_incident_info: dict | None = None,
) -> str:
    """USE_BEDROCK=false 保底模板：用固定格式組裝建議書，不呼叫 LLM。
    
    [2026-08-01新增] merged_incident_info：同路段多事件合併時顯示所有事件資訊。
    """
    parts = []
    
    # ★ 情境1：同路段多事件合併報告
    if merged_incident_info and merged_incident_info.get("count", 0) > 1:
        parts.append("═" * 50)
        parts.append("【⚠️ 同路段多事件合併交控建議書】")
        parts.append("═" * 50)
        parts.append(f"合併事件數量：{merged_incident_info['count']} 件")
        parts.append(f"合併事件ID：{', '.join(merged_incident_info['event_ids'])}")
        parts.append("")
        parts.append("【各事件詳情】")
        for i, (eid, desc) in enumerate(zip(merged_incident_info['event_ids'], merged_incident_info.get('descriptions', [])), 1):
            parts.append(f"  {i}. {eid}: {desc}")
        parts.append("")
        parts.append("【ETE 合併計算說明】")
        parts.append(f"  • 各事件最大 ETE：{merged_incident_info['max_ete_minutes']} 分鐘")
        parts.append(f"  • 多事件協調延遲：+{(merged_incident_info['count'] - 1) * 15} 分鐘")
        parts.append(f"    （每多一事件增加 15 分鐘協調時間）")
        parts.append(f"  • 合併後總 ETE：{merged_incident_info['merged_ete_minutes']} 分鐘")
        parts.append("─" * 50)
        parts.append("")
    else:
        parts.append(f"【交控建議書】事件 {incident.event_id}")
    
    parts.append(f"事件描述：{incident.description}（{incident.location}）")
    parts.append(f"命中條款：{', '.join(sorted({h.clause_id for h in sensing.rule_hits}))}")
    parts.append(f"交通分級：{sensing.traffic_level} 級")

    # [2026-07-28架構複查新增：回應「系統架構_v2_實作版.md」仍待確認第2點]
    # R4 的 saturated_but_retained 例外（唯一合格候選仍飽和時保留為主線）之前完全沒有
    # 反映在建議書文字裡——建議主要路線的文字跟正常暢通路線一模一樣，會誤導指揮官以為
    # 這條路線是安全的。這裡先算出哪些路段有這個 finding，供下面加註警語。
    saturated_retained_ids = {
        seg_id
        for f in (route_plan.findings if route_plan else [])
        if f.finding_code == "SATURATED_BUT_RETAINED"
        for seg_id in f.segment_ids
    }

    if route_plan and route_plan.primary:
        primary_note = "（⚠️ 此路線仍處於飽和狀態，為目前唯一可用選項，非暢通路線）" \
            if route_plan.primary.segment_id in saturated_retained_ids else ""
        parts.append(f"建議主要替代路線：{route_plan.primary.name}{primary_note}")
    if route_plan and route_plan.secondary:
        secondary_note = "（⚠️ 此路線仍處於飽和狀態，為目前唯一可用選項，非暢通路線）" \
            if route_plan.secondary.segment_id in saturated_retained_ids else ""
        parts.append(f"建議次要替代路線：{route_plan.secondary.name}{secondary_note}")
    if route_plan:
        for exc in route_plan.excluded:
            parts.append(f"  排除：{exc.name}（{_reason_code_to_text(exc.reason_code, exc)}）")

    # C2 號誌建議：SOP-1 命中時的一般性延燈建議；若有 SATURATED_BUT_RETAINED，額外註明
    # 這是「不得已保留飽和路線」專屬的長綠燈時制動作（routing.py 的 finding.evidence 已算好）
    sop1_hits = [h for h in sensing.rule_hits if h.clause_id == "SOP-1"]
    if sop1_hits:
        parts.append(f"號誌調整：替代路線綠燈時間增加 25%，調整期間 {incident.timestamp.strftime('%H:%M')} 至 {ete.recovery_at.split(' ')[-1]}")
    if saturated_retained_ids and route_plan:
        for f in route_plan.findings:
            if f.finding_code == "SATURATED_BUT_RETAINED":
                parts.append(f"  ⚠️ 保留飽和路線特別處置：{f.evidence.get('action', '啟動長綠燈時制')}（飽和度 {f.evidence.get('saturation_score')}）")

    # C3 聯動建議
    sop3_hits = [h for h in sensing.rule_hits if h.clause_id == "SOP-3"]
    sop5_hits = [h for h in sensing.rule_hits if h.clause_id == "SOP-5"]
    if sop3_hits:
        parts.append("聯動建議：通知北捷啟動過站不停措施，調度接駁專車，引導至替代站點 BS_MRT_BL18")
    if sop5_hits:
        # [2026-07-28架構複查修正：回應SPEC-O2「§5必含COUNT_INTERSECTIONS」]
        # SOP原文（emergency_traffic_sop.json §5）：「產出人工指揮派遣建議（受影響路段、
        # 警力人數每路口2人、估計持續時間）；CMS加註「<路段>號誌故障，請依現場指揮通行」」。
        # count_affected_intersections() 之前寫好但從沒被呼叫過，這裡補上，警力人數=路口數×2。
        from src.routing import count_affected_intersections
        intersection_count = count_affected_intersections(bundle, incident.affected_segment)
        police_count = intersection_count * 2
        parts.append(
            f"聯動建議：派遣人力支援 {police_count} 人（{incident.affected_segment} 沿線 "
            f"{intersection_count} 個路口，每路口2人），預計持續 {ete.minutes} 分鐘"
        )
        # location 欄位有時已包含「故障」字樣（例如真實資料 EVT_003 的 location 是
        # 「信義威秀/ATT4FUN周邊路燈號誌故障」），此時不重複加「號誌故障」避免語句重複。
        fault_suffix = "，請依現場指揮通行" if "故障" in incident.location else "號誌故障，請依現場指揮通行"
        parts.append(f"CMS文字：「{incident.location}{fault_suffix}」")

    parts.append(f"預計恢復時間：{ete.recovery_at}（ETE {ete.minutes} 分鐘）")

    return "\n".join(parts)


def _generate_c4_fallback(
    incident: Incident,
    route_plan: RoutePlan | None,
    ete: EteEstimate,
    multilingual: bool,
) -> Notification:
    """USE_BEDROCK=false 保底模板：固定格式簡訊（含日文/韓文加分項）。
    
    多語版本會將地點、事件類型、改道建議翻譯成對應語言。
    """
    route_name_zh = route_plan.primary.name if (route_plan and route_plan.primary) else "請依現場指揮"
    
    # 事件類型翻譯對照表
    type_translations = {
        "Road_Collapse_Accident": {
            "zh": "路面塌陷事故",
            "en": "road collapse",
            "ja": "路面陥没事故",
            "ko": "도로 붕괴 사고",
        },
        "Traffic_Accident": {
            "zh": "交通事故",
            "en": "traffic accident",
            "ja": "交通事故",
            "ko": "교통사고",
        },
        "Crowd_Surge_Injury": {
            "zh": "人群推擠傷亡",
            "en": "crowd surge incident",
            "ja": "群衆事故",
            "ko": "군중 밀집 사고",
        },
        "Power_Failure": {
            "zh": "號誌故障",
            "en": "signal malfunction",
            "ja": "信号機故障",
            "ko": "신호등 고장",
        },
        "Vehicle_Fire": {
            "zh": "車輛起火",
            "en": "vehicle fire",
            "ja": "車両火災",
            "ko": "차량 화재",
        },
        "Large_Event_Dispersal": {
            "zh": "大型活動散場",
            "en": "large event dispersal",
            "ja": "大型イベント終了",
            "ko": "대형 행사 산개",
        },
    }
    
    # 常見地點翻譯對照表
    location_translations = {
        "捷運國父紀念館站": {
            "en": "Sun Yat-sen Memorial Hall MRT Station",
            "ja": "MRT国父記念館駅",
            "ko": "국부기념관역",
        },
        "捷運市政府站": {
            "en": "Taipei City Hall MRT Station",
            "ja": "MRT市政府駅",
            "ko": "시청역",
        },
        "台北101": {
            "en": "Taipei 101",
            "ja": "台北101",
            "ko": "타이베이 101",
        },
        "大巨蛋": {
            "en": "Taipei Dome",
            "ja": "台北ドーム",
            "ko": "타이베이 돔",
        },
        "信義威秀": {
            "en": "Shin Kong Mitsukoshi Xinyi",
            "ja": "信義エリア",
            "ko": "신의 지구",
        },
        "光復南路": {
            "en": "Guangfu South Road",
            "ja": "光復南路",
            "ko": "광푸남로",
        },
        "忠孝東路": {
            "en": "Zhongxiao East Road",
            "ja": "忠孝東路",
            "ko": "중샤오동로",
        },
        "市民大道": {
            "en": "Civic Boulevard",
            "ja": "市民大道",
            "ko": "시민대로",
        },
        "基隆路": {
            "en": "Keelung Road",
            "ja": "基隆路",
            "ko": "지룽로",
        },
        "松高路": {
            "en": "Songgao Road",
            "ja": "松高路",
            "ko": "송가오로",
        },
    }
    
    # 無替代路線時的翻譯
    no_route_translations = {
        "zh": "請依現場指揮",
        "en": "follow on-site instructions",
        "ja": "現場の指示に従ってください",
        "ko": "현장 지시에 따르세요",
    }
    
    def translate_location(loc: str, lang: str) -> str:
        """嘗試翻譯地點名稱，找不到則保留原文。"""
        if lang == "zh":
            return loc
        for zh_key, trans in location_translations.items():
            if zh_key in loc:
                return loc.replace(zh_key, trans.get(lang, zh_key))
        return loc  # 找不到翻譯，保留原文
    
    def get_type_text(t: str, lang: str) -> str:
        """取得事件類型的翻譯文字。"""
        if t in type_translations:
            return type_translations[t].get(lang, t)
        return t
    
    def get_route_name(lang: str) -> str:
        """取得改道建議的翻譯文字。"""
        if route_plan and route_plan.primary:
            return translate_location(route_plan.primary.name, lang)
        return no_route_translations.get(lang, "請依現場指揮")
    
    # 中文版（必填）
    type_zh = get_type_text(incident.type, "zh")
    zh = f"交通事故通知：{incident.location}發生{type_zh}，建議改道{route_name_zh}，預計{ete.minutes}分鐘後恢復。"

    en: str | None = None
    ja: str | None = None
    ko: str | None = None

    if multilingual:
        loc_en = translate_location(incident.location, "en")
        loc_ja = translate_location(incident.location, "ja")
        loc_ko = translate_location(incident.location, "ko")
        
        type_en = get_type_text(incident.type, "en")
        type_ja = get_type_text(incident.type, "ja")
        type_ko = get_type_text(incident.type, "ko")
        
        route_en = get_route_name("en")
        route_ja = get_route_name("ja")
        route_ko = get_route_name("ko")
        
        en = f"Traffic alert: {type_en} at {loc_en}. Suggested detour via {route_en}. ETA {ete.minutes} min."
        ja = f"交通警報：{loc_ja}で{type_ja}発生。迂回路：{route_ja}、復旧予定：{ete.minutes}分後。"
        ko = f"교통 알림: {loc_ko}에서 {type_ko} 발생. 우회 경로: {route_ko}, 예상 복구: {ete.minutes}분 후."

    return Notification(zh=zh, en=en, ja=ja, ko=ko)


def generate_report(
    incident: Incident,
    sensing: SensingResult,
    route_plan: RoutePlan | None,
    ete: EteEstimate,
    advisory: BedrockAdvisory | None,
    bundle: NormalizedDataBundle,
    merged_incident_info: dict | None = None,
) -> tuple[str | None, Notification | None]:
    """C1-C4：LLM 生成，唯讀轉換——只能表達已經算好的事實，不得改寫任何數字/路段/條款編號。

    回傳 (交控建議書全文, 多語簡訊物件)。
    失敗時對應欄位為 None，不拋例外（永不沉默原則）。

    [2026-07-28架構複查新增] `bundle` 參數：SOP-5 的警力人數需要
    `routing.count_affected_intersections()` 算受影響路口數，見 `_generate_c1_c3_fallback`。

    [2026-08-01 修正：LLM 失敗時退回模板，不再直接放棄]
    ------------------------------------------------------
    原本的分支是「`USE_BEDROCK` 旗標為 true → 走 LLM，例外 → 回 None」。問題在於
    旗標說的是「**允不允許**用 Bedrock」，不是「Bedrock **現在通不通**」。兩者一旦
    分歧（憑證過期、模型未開通、斷網），建議書與簡訊就整個變成 None。

    實測憑證過期的情況：決策週期 3.5 秒跑完、黃金值全對，但
    `degraded=['C1_FAILED','C4_FAILED']`、**建議書 0 字、簡訊全空**——
    而同一份資料在 `USE_BEDROCK=false` 之下明明能產出完整的模板版建議書與四語簡訊。
    等於「因為想要更好的版本，結果連堪用的版本都不給了」。

    改成兩段式：先試 LLM，失敗就退模板。只有連模板都組不出來（那是資料層的問題，
    不是 LLM 的問題）才回 None。這讓憑證過期從「Demo 崩潰」降級成「文字比較樸素」。
    """
    from concurrent.futures import ThreadPoolExecutor

    from src.llm import bedrock_enabled

    use_bedrock = bedrock_enabled()
    multilingual = sensing.multilingual_required

    # [2026-08-01 並行化] C1-C3 與 C4 之間沒有任何資料依賴——兩者都只讀已經算好的
    # incident/sensing/route_plan/ete。原本卻是序列執行，實測 20.8s + 8.6s = 29.4s
    # 白白等成一條線。改並行後上限是兩者的最大值，不是總和。
    #
    # 用執行緒而不是 asyncio：boto3 是同步 client，而 generate_report() 的呼叫端
    # （orchestrator 的 EXECUTE 階段）目前是同步函式，改成 async 會一路往上傳染。
    # 兩個 I/O-bound 呼叫用執行緒完全足夠，GIL 在等待網路時會釋放。
    if use_bedrock:
        with ThreadPoolExecutor(max_workers=2) as pool:
            report_future = pool.submit(
                _generate_with_llm, incident, sensing, route_plan, ete, bundle
            )
            notif_future = pool.submit(
                _generate_notification_with_llm, incident, route_plan, ete, multilingual
            )

            try:
                report_text: str | None = report_future.result()
            except Exception as e:
                logger.warning(f"C1-C3 LLM 生成失敗，退回固定模板: {e}")
                report_text = None

            try:
                notification: Notification | None = notif_future.result()
            except Exception as e:
                logger.warning(f"C4 LLM 生成失敗，退回固定模板: {e}")
                notification = None
    else:
        report_text = None
        notification = None

    # 模板保底。LLM 沒開、或開了但打不通，都走到這裡——旗標說的是「允不允許用
    # Bedrock」，不是「Bedrock 現在通不通」，兩者分歧時不該連堪用的版本都不給。
    if report_text is None:
        try:
            report_text = _generate_c1_c3_fallback(incident, sensing, route_plan, ete, bundle)
        except Exception:
            logger.exception("C1-C3 模板組裝也失敗")
            report_text = None

    if notification is None:
        try:
            notification = _generate_c4_fallback(incident, route_plan, ete, multilingual)
        except Exception:
            logger.exception("C4 模板組裝也失敗")
            notification = None

    return report_text, notification


def _invoke_bedrock_converse(system_prompt: str, user_message: str) -> str:
    """呼叫 Bedrock Converse API（Claude）生成文字。

    這是 C1-C4 與 M4B 解釋鏈共用的底層 LLM 呼叫函式。
    失敗時拋例外，由上層 try/except 處理降級。

    [2026-08-01] 實作搬到 `src/llm.py`，這裡保留為薄轉接層。保留原因有二：
    `decision_trace._invoke_m4b_llm()` 以這個名字 import，且 `tests/test_a2_agent.py`
    以 monkeypatch 攔這個名字讓整個決策週期離線可測——這是既有的測試接縫，
    不值得為了「少一層」而破壞它。

    搬家換到的實質好處是逾時：原本這裡的 boto3 client 沒有任何 timeout 設定，
    網路不穩時 C1-C3 生成會無限期卡住整個決策週期。
    """
    from src.llm import get_report_model_id, invoke_converse

    # [2026-08-01] max_tokens 2000 → 800，並改用 Haiku。
    # 輸出長度直接決定延遲：實測 1508 字要 20.8 秒。2000 tokens 的上限等於放任
    # 模型寫論文，而指揮中心要的是一頁就能看完的建議書。prompt 端也加了字數規定
    # （prompts/report.txt），這裡是硬上限——prompt 沒被遵守時仍有一道閘。
    return invoke_converse(
        system_prompt,
        user_message,
        max_tokens=800,
        temperature=0.3,
        model_id=get_report_model_id(),
    )


def _generate_with_llm(
    incident: Incident,
    sensing: SensingResult,
    route_plan: RoutePlan | None,
    ete: EteEstimate,
    bundle: NormalizedDataBundle,
    merged_incident_info: dict | None = None,
) -> str:
    """使用 Bedrock LLM 生成 C1-C3 建議書。"""
    from src.risk_projection import build_risk_block, project_risks

    system_prompt = _load_prompt("report.txt")
    facts_block = build_facts_block(incident, sensing, route_plan, ete, bundle)
    
    # 如果有合併事件，加入合併資訊
    if merged_incident_info and merged_incident_info.get("count", 0) > 1:
        merged_block = (
            f"\n\n【同路段多事件合併資訊】\n"
            f"合併事件數量: {merged_incident_info['count']} 件\n"
            f"合併事件ID: {', '.join(merged_incident_info['event_ids'])}\n"
            f"各事件最大 ETE: {merged_incident_info['max_ete_minutes']} 分鐘\n"
            f"合併後總 ETE: {merged_incident_info['merged_ete_minutes']} 分鐘\n"
            f"（計算方式: max(各事件ETE) + (事件數-1)×15分鐘）"
        )
        facts_block += merged_block
    

    # [2026-08-01] 二階效應推演一併注入。跟事實區塊同樣是「LLM 只能引用、
    # 不能改寫」——風險的時間點、數值、對策全部由 `risk_projection` 算好。
    # 推演失敗只是少一段內容，不能讓整份建議書生不出來。
    try:
        projection = project_risks(incident, route_plan, sensing, bundle, ete.minutes)
        risk_block = build_risk_block(projection)
    except Exception:  # noqa: BLE001
        logger.exception("風險推演失敗，建議書不含後續風險段落")
        risk_block = ""

    user_message = (
        f"請根據以下事實資料生成交控建議書（含號誌調整、聯動建議與後續風險）：\n\n"
        f"{facts_block}\n\n{risk_block}"
    )

    return _invoke_bedrock_converse(system_prompt, user_message)


def _generate_notification_with_llm(
    incident: Incident,
    route_plan: RoutePlan | None,
    ete: EteEstimate,
    multilingual: bool,
) -> Notification:
    """使用 Bedrock LLM 生成 C4 多語簡訊。"""
    system_prompt = _load_prompt("notification.txt")

    route_name = route_plan.primary.name if (route_plan and route_plan.primary) else "請依現場指揮"
    facts = (
        f"事故位置: {incident.location}\n"
        f"事故類型: {incident.type}\n"
        f"建議改道: {route_name}\n"
        f"預計恢復時間: {ete.recovery_at}（{ete.minutes} 分鐘）"
    )

    if multilingual:
        user_message = (
            f"請根據以下事實生成中文、英文、日文、韓文四個版本的交通簡訊通知（各不超過100字/160字元）：\n\n{facts}\n\n"
            f"請以 JSON 格式回覆：{{\"zh\": \"...\", \"en\": \"...\", \"ja\": \"...\", \"ko\": \"...\"}}"
        )
    else:
        user_message = f"請根據以下事實生成中文交通簡訊通知（不超過100字）：\n\n{facts}"

    # 走 `_invoke_bedrock_converse` 而不是直接呼叫 `llm.invoke_converse`：
    # 那個名字是既有的**測試接縫**（tests/test_a2_agent.py 以 monkeypatch 攔它
    # 讓整個決策週期離線可測）。繞過去的話測試會真的打網路——實測套件從 2.3 秒
    # 變成 29 秒，而且變成依賴憑證與連線。
    text = _invoke_bedrock_converse(system_prompt, user_message)

    # 嘗試解析 JSON（多語時）
    if multilingual:
        import json
        try:
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                parsed = json.loads(text[start:end])
                return Notification(
                    zh=parsed.get("zh", text),
                    en=parsed.get("en"),
                    ja=parsed.get("ja"),
                    ko=parsed.get("ko"),
                )
        except (json.JSONDecodeError, KeyError):
            pass
        return Notification(zh=text, en=None, ja=None, ko=None)
    else:
        return Notification(zh=text, en=None, ja=None, ko=None)
