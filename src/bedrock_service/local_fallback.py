"""本機關鍵字比對，USE_BEDROCK=false 或雲端呼叫失敗時的保底路徑。純確定性、零 LLM。

參考 spec：`.kiro/specs/m3-bedrock-advisor/K3-sop-rag/design.md` 第四節。
"""

from __future__ import annotations

from src.bedrock_service.sop_data import SOP_DATA, SopMatch

KEYWORD_MAP: dict[int, list[str]] = {
    1: ["飽和", "擁塞", "A級", "B級", "紅燈", "黃燈", "級別", "Saturation"],
    2: ["車禍", "路障", "塌陷", "封閉", "Closed", "Blocked", "替代路", "疏散", "上游", "下游"],
    3: ["捷運", "BL17", "接駁", "過站不停", "人流", "Growth_Rate", "User_Count"],
    4: ["大巨蛋", "散場", "DOME", "峰值"],
    5: ["號誌", "故障", "Power_Failure", "人工指揮"],
    6: ["漫遊", "Roaming", "多語", "簡訊", "通報"],
    7: ["ETE", "恢復時間", "base_clearance", "congestion_penalty", "公式"],
}
"""逐字抄自 K3-sop-rag/design.md 第四節，這是資料不是邏輯，不得自行增減關鍵字。"""

RELEVANCE_THRESHOLD = 0.3


def query_local(question: str) -> list[SopMatch]:
    """關鍵字命中比對，取前 3、過濾低於 RELEVANCE_THRESHOLD 的。

    score = hit_count / len(keywords)，依分數降序排序取前 3。
    """
    question_lower = question.lower()
    scores: dict[int, float] = {}

    for section_number, keywords in KEYWORD_MAP.items():
        hit_count = sum(1 for kw in keywords if kw.lower() in question_lower)
        if hit_count > 0:
            scores[section_number] = hit_count / len(keywords)

    # 依分數降序，取前 3
    sorted_sections = sorted(scores.items(), key=lambda x: x[1], reverse=True)[:3]

    results: list[SopMatch] = []
    for section_number, score in sorted_sections:
        if score < RELEVANCE_THRESHOLD:
            continue
        section = SOP_DATA[section_number]
        results.append(SopMatch(
            section_number=section.section_number,
            title=section.title,
            content=section.content,
            relevance_score=round(score, 3),
        ))

    return results
