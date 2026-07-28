"""本機關鍵字比對，USE_BEDROCK=false 或雲端呼叫失敗時的保底路徑。純確定性、零 LLM。

參考 spec：`.kiro/specs/m3-bedrock-advisor/K3-sop-rag/design.md` 第四節。
"""

from __future__ import annotations

from src.bedrock_service.sop_data import SopMatch

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

    TODO(Kiro): 依 design.md 第四節「比對邏輯」實作：
    score = hit_count / len(keywords)，依分數排序取前3。
    """
    raise NotImplementedError("見 K3-sop-rag/design.md 第四節")
