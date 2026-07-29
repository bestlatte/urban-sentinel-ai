"""A3 ETE 計算 + C1-C4 建議書/號誌/聯動/簡訊生成。

參考 spec：`.kiro/specs/m4-decision-reporting/requirements.md`（唯一權威，含 ETE
公式、三筆黃金驗收值、C1-C4 提示詞契約、失敗降級規則）。**這不是**
`m4-explanation-chain-and-orchestrator/`（那是解釋鏈/Orchestrator 核心邏輯，
命名雖然都帶「模組四」但範圍不同，見該資料夾與本檔案的分工說明）。

C1~C4 一律由 A2 編排觸發，本模組不得被繞過直接呼叫（01-module-boundaries.md 規則9）。
"""

from __future__ import annotations

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


def _build_facts_block(
    incident: Incident,
    sensing: SensingResult,
    route_plan: RoutePlan | None,
    ete: EteEstimate,
) -> str:
    """把確定性事實組成文字塊注入 prompt，LLM 只能引用不能改寫。"""
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
) -> str:
    """USE_BEDROCK=false 保底模板：用固定格式組裝建議書，不呼叫 LLM。"""
    parts = []
    parts.append(f"【交控建議書】事件 {incident.event_id}")
    parts.append(f"事件描述：{incident.description}（{incident.location}）")
    parts.append(f"命中條款：{', '.join(sorted({h.clause_id for h in sensing.rule_hits}))}")
    parts.append(f"交通分級：{sensing.traffic_level} 級")

    if route_plan and route_plan.primary:
        parts.append(f"建議主要替代路線：{route_plan.primary.name}")
    if route_plan and route_plan.secondary:
        parts.append(f"建議次要替代路線：{route_plan.secondary.name}")
    if route_plan:
        for exc in route_plan.excluded:
            parts.append(f"  排除：{exc.name}（{_reason_code_to_text(exc.reason_code, exc)}）")

    # C2 號誌建議
    sop1_hits = [h for h in sensing.rule_hits if h.clause_id == "SOP-1"]
    if sop1_hits:
        parts.append(f"號誌調整：替代路線綠燈時間增加 25%，調整期間 {incident.timestamp.strftime('%H:%M')} 至 {ete.recovery_at.split(' ')[-1]}")

    # C3 聯動建議
    sop3_hits = [h for h in sensing.rule_hits if h.clause_id == "SOP-3"]
    sop5_hits = [h for h in sensing.rule_hits if h.clause_id == "SOP-5"]
    if sop3_hits:
        parts.append("聯動建議：通知北捷啟動過站不停措施，調度接駁專車，引導至替代站點 BS_MRT_BL18")
    if sop5_hits:
        parts.append(f"聯動建議：派遣人力支援，預計持續 {ete.minutes} 分鐘")

    parts.append(f"預計恢復時間：{ete.recovery_at}（ETE {ete.minutes} 分鐘）")

    return "\n".join(parts)


def _generate_c4_fallback(
    incident: Incident,
    route_plan: RoutePlan | None,
    ete: EteEstimate,
    multilingual: bool,
) -> Notification:
    """USE_BEDROCK=false 保底模板：固定格式簡訊。"""
    route_name = route_plan.primary.name if (route_plan and route_plan.primary) else "請依現場指揮"
    zh = f"交通事故通知：{incident.location}發生{incident.type}，建議改道{route_name}，預計{ete.minutes}分鐘後恢復。"

    en: str | None = None
    if multilingual:
        en = f"Traffic alert: incident at {incident.location}, suggested detour via {route_name}, ETA {ete.minutes} min."

    return Notification(zh=zh, en=en)


def generate_report(
    incident: Incident,
    sensing: SensingResult,
    route_plan: RoutePlan | None,
    ete: EteEstimate,
    advisory: BedrockAdvisory | None,
) -> tuple[str | None, Notification | None]:
    """C1-C4：LLM 生成，唯讀轉換——只能表達已經算好的事實，不得改寫任何數字/路段/條款編號。

    回傳 (交控建議書全文, 多語簡訊物件)。
    失敗時對應欄位為 None，不拋例外（永不沉默原則）。
    """
    import os

    use_bedrock = os.getenv("USE_BEDROCK", "true").lower() == "true"
    multilingual = sensing.multilingual_required

    # C1-C3 建議書
    report_text: str | None = None
    try:
        if use_bedrock:
            report_text = _generate_with_llm(incident, sensing, route_plan, ete)
        else:
            report_text = _generate_c1_c3_fallback(incident, sensing, route_plan, ete)
    except Exception:
        report_text = None

    # C4 簡訊
    notification: Notification | None = None
    try:
        if use_bedrock:
            notification = _generate_notification_with_llm(incident, route_plan, ete, multilingual)
        else:
            notification = _generate_c4_fallback(incident, route_plan, ete, multilingual)
    except Exception:
        notification = None

    return report_text, notification


def _generate_with_llm(
    incident: Incident,
    sensing: SensingResult,
    route_plan: RoutePlan | None,
    ete: EteEstimate,
) -> str:
    """使用 Bedrock LLM 生成 C1-C3 建議書。

    TODO(Kiro): Phase 7 完成 Agent 後接入真正的 LLM 呼叫。
    目前暫用保底模板，確保流程不中斷。
    """
    return _generate_c1_c3_fallback(incident, sensing, route_plan, ete)


def _generate_notification_with_llm(
    incident: Incident,
    route_plan: RoutePlan | None,
    ete: EteEstimate,
    multilingual: bool,
) -> Notification:
    """使用 Bedrock LLM 生成 C4 多語簡訊。

    TODO(Kiro): Phase 7 完成 Agent 後接入真正的 LLM 呼叫。
    """
    return _generate_c4_fallback(incident, route_plan, ete, multilingual)
