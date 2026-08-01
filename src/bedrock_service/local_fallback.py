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

FULL_MATCH_HITS = 3
"""命中幾個關鍵字算「完全相關」（score = 1.0）。

[2026-08-01 實測修正：偏離 K3-sop-rag/design.md §4 的公式，理由如下]

design.md §4 原本的公式是 `score = hit_count / len(keywords)`，配
`RELEVANCE_THRESHOLD = 0.3`。問題是分母是**該條款的關鍵字總數**，而各條款關鍵字
數量差很多（§2 有 10 個、§4 只有 4 個），導致過關門檻完全不一致：

    §2 需命中 3/10 個關鍵字   §1 需 3/8   §3 需 3/9   §4 需 2/4   §7 需 2/5

實測「路面塌陷事故的 SOP 條款怎麼規定？」只命中「塌陷」→ 0.1 → 被濾掉，
`query_sop` 回傳 `sections: []`。也就是說**自然語言問句幾乎永遠查不到 SOP**，
W1 的條款依據鏈整條是空的（Agent 實測會連查兩次都拿到空結果，然後回答
「目前 SOP 未涵蓋路面塌陷事故」——這是錯的，§2 就是在講這個）。

改成固定分母後語意變成「命中越多越相關，命中 3 個以上視為完全相關」，
各條款門檻一致，且 1 個關鍵字命中（0.333）就足以過關——KEYWORD_MAP 裡的詞
（「塌陷」「號誌」「漫遊」）本來就夠具體，命中一個就有檢索價值。

**沒有動 KEYWORD_MAP**（design.md 明訂「這是資料不是邏輯，不得自行增減關鍵字」），
也沒有動 RELEVANCE_THRESHOLD 常數值，只改分母。前 3 名排序與零命中回空的行為不變。
"""


def query_local(question: str) -> list[SopMatch]:
    """關鍵字命中比對，取前 3、過濾低於 RELEVANCE_THRESHOLD 的。

    score = min(1.0, hit_count / FULL_MATCH_HITS)，依分數降序排序取前 3。
    分母的選擇見 `FULL_MATCH_HITS` 的說明。
    """
    question_lower = question.lower()
    scores: dict[int, float] = {}

    for section_number, keywords in KEYWORD_MAP.items():
        hit_count = sum(1 for kw in keywords if kw.lower() in question_lower)
        if hit_count > 0:
            scores[section_number] = min(1.0, hit_count / FULL_MATCH_HITS)

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
